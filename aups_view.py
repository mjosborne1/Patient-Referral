"""Turn an AU Patient Summary document Bundle into a view model for rendering.

The view is driven by the Composition: one block per ``Composition.section`` in
document order, with each section's entries resolved against the Bundle. It handles
the shapes found in the HL7 AU test data set (au-fhir-test-data/au-patient-summary):

- ``urn:uuid`` and ``Type/id`` references, and contained resources (``#id``)
- ``section.emptyReason`` (no entries, with a reason)
- "no known X" assertions (e.g. SNOMED 716186003 No known allergy), shown as a
  statement rather than as a list item
- narrative-only sections (e.g. Patient Story), whose XHTML is sanitised
- Observation panels (``hasMember``) and component values (e.g. blood pressure)
- nested sections
"""
from __future__ import annotations

from html import escape
from html.parser import HTMLParser

from fhirutils import format_fhir_date

LOINC = 'http://loinc.org'
SCT = 'http://snomed.info/sct'
IPS_ABSENT = 'http://hl7.org/fhir/uv/ips/CodeSystem/absent-unknown-uv-ips'

# LOINC section code -> (standard heading, Font Awesome 6 icon, Bootstrap colour)
SECTION_META = {
    '48765-2': ('Allergies & Intolerances', 'fa-hand-dots', 'danger'),
    '10160-0': ('Medications', 'fa-pills', 'primary'),
    '11450-4': ('Problems', 'fa-notes-medical', 'warning'),
    '11369-6': ('Immunisations', 'fa-syringe', 'success'),
    '30954-2': ('Results', 'fa-vial', 'info'),
    '47519-4': ('Procedures', 'fa-bed-pulse', 'secondary'),
    '11348-0': ('Past History', 'fa-clock-rotate-left', 'secondary'),
    '10162-6': ('Pregnancy', 'fa-baby', 'info'),
    '29762-2': ('Social History', 'fa-people-group', 'secondary'),
    '81338-6': ('Patient Story', 'fa-comment-medical', 'primary'),
    '8716-3': ('Vital Signs', 'fa-heart-pulse', 'danger'),
    '46264-8': ('Medical Devices', 'fa-stethoscope', 'secondary'),
    '47420-5': ('Functional Status', 'fa-person-walking', 'secondary'),
    '18776-5': ('Plan of Care', 'fa-clipboard-list', 'primary'),
    '42348-3': ('Advance Directives', 'fa-file-signature', 'secondary'),
    '104605-1': ('Alerts', 'fa-triangle-exclamation', 'danger'),
}
DEFAULT_META = (None, 'fa-file-medical', 'secondary')

# Codes that assert the *absence* of something. These are rendered as a statement.
NO_KNOWN_CODES = {
    (SCT, '716186003'),   # No known allergy
    (SCT, '409137002'),   # No known drug allergy
    (SCT, '429625007'),   # No known food allergy
    (SCT, '428607008'),   # No known environmental allergy
    (SCT, '787481004'),   # No known medications
    (SCT, '182849000'),   # No drug therapy prescribed
    (SCT, '160245001'),   # No current problems or disability
    (IPS_ABSENT, 'no-allergy-info'),
    (IPS_ABSENT, 'no-known-allergies'),
    (IPS_ABSENT, 'no-known-medication-allergies'),
    (IPS_ABSENT, 'no-known-environmental-allergies'),
    (IPS_ABSENT, 'no-known-food-allergies'),
    (IPS_ABSENT, 'no-medication-info'),
    (IPS_ABSENT, 'no-known-medications'),
    (IPS_ABSENT, 'no-problem-info'),
    (IPS_ABSENT, 'no-known-problems'),
    (IPS_ABSENT, 'no-immunization-info'),
    (IPS_ABSENT, 'no-known-immunizations'),
    (IPS_ABSENT, 'no-procedure-info'),
    (IPS_ABSENT, 'no-known-procedures'),
    (IPS_ABSENT, 'no-device-info'),
    (IPS_ABSENT, 'no-known-devices'),
}

EMPTY_REASON_TEXT = {
    'nilknown': 'Nil known',
    'notasked': 'Not asked',
    'withheld': 'Information withheld',
    'unavailable': 'Information unavailable',
    'notstarted': 'Not started',
    'closed': 'Closed',
}

# Columns per resource type; each row is a dict keyed by these column names.
COLUMNS = {
    'Condition': ['Problem', 'Status', 'Onset', 'Resolved', 'Notes'],
    'AllergyIntolerance': ['Substance', 'Reaction', 'Criticality', 'Status', 'Recorded'],
    'MedicationStatement': ['Medicine', 'Dosage', 'Status', 'Date'],
    'MedicationRequest': ['Medicine', 'Dosage', 'Status', 'Date'],
    'Immunization': ['Vaccine', 'Date', 'Status', 'Notes'],
    'Procedure': ['Procedure', 'Date', 'Status', 'Reason'],
    'Observation': ['Observation', 'Result', 'Date', 'Interpretation'],
    'DiagnosticReport': ['Report', 'Conclusion', 'Date', 'Status'],
    'Device': ['Device', 'Status'],
    'DeviceUseStatement': ['Device', 'Status', 'Date'],
    'Flag': ['Alert', 'Status', 'Period'],
    'CarePlan': ['Plan', 'Status', 'Period'],
    'Consent': ['Consent', 'Status', 'Date'],
    'ClinicalImpression': ['Assessment', 'Status', 'Date'],
}
DEFAULT_COLUMNS = ['Item', 'Type']


# --------------------------------------------------------------------------- helpers

def cc_text(cc, default=''):
    """Best human display for a CodeableConcept: text, then first coding display, then code."""
    if not cc:
        return default
    if cc.get('text'):
        return cc['text']
    for coding in cc.get('coding', []):
        if coding.get('display'):
            return coding['display']
    for coding in cc.get('coding', []):
        if coding.get('code'):
            return coding['code']
    return default


def ccs_text(ccs):
    return ', '.join(t for t in (cc_text(c) for c in ccs or []) if t)


def human_name(names):
    if not names:
        return ''
    n = next((x for x in names if x.get('use') == 'official'), names[0])
    if n.get('text'):
        return n['text']
    parts = list(n.get('prefix', [])) + list(n.get('given', [])) + ([n['family']] if n.get('family') else [])
    return ' '.join(parts)


def fmt_date(value):
    return format_fhir_date(value) if value else ''


def fmt_quantity(q):
    if not q:
        return ''
    value = q.get('value')
    unit = q.get('unit') or q.get('code') or ''
    comparator = q.get('comparator', '')
    if value is None:
        return ''
    return f"{comparator}{value:g} {unit}".strip() if isinstance(value, (int, float)) else f"{comparator}{value} {unit}".strip()


def fmt_range(r):
    if not r:
        return ''
    low, high = fmt_quantity(r.get('low')), fmt_quantity(r.get('high'))
    if low and high:
        return f'{low} – {high}'
    return f'≥ {low}' if low else (f'≤ {high}' if high else '')


def fmt_period(p):
    if not p:
        return ''
    start, end = fmt_date(p.get('start')), fmt_date(p.get('end'))
    if start and end:
        return f'{start} – {end}'
    return start or (f'until {end}' if end else '')


def fmt_age(a):
    return f"age {fmt_quantity(a)}" if a else ''


def fmt_choice(res, prefix):
    """Format a FHIR choice[x] element such as onset[x], effective[x] or value[x]."""
    for suffix, fn in (
        ('DateTime', fmt_date), ('Date', fmt_date), ('Instant', fmt_date),
        ('Period', fmt_period), ('Age', fmt_age), ('Range', fmt_range),
        ('Quantity', fmt_quantity), ('CodeableConcept', cc_text),
        ('String', str), ('Integer', str), ('Boolean', lambda v: 'Yes' if v else 'No'),
        ('Ratio', lambda r: f"{fmt_quantity(r.get('numerator'))} / {fmt_quantity(r.get('denominator'))}"),
    ):
        key = prefix + suffix
        if key in res:
            return fn(res[key])
    return ''


def status_code(cc):
    """Return the code of a status CodeableConcept (e.g. clinicalStatus), else its text."""
    if not cc:
        return ''
    for coding in cc.get('coding', []):
        if coding.get('code'):
            return coding['code']
    return cc.get('text', '')


def is_no_known(cc):
    for coding in (cc or {}).get('coding', []):
        if (coding.get('system'), coding.get('code')) in NO_KNOWN_CODES:
            return True
    return False


def notes_text(res):
    return ' '.join(n.get('text', '') for n in res.get('note', []) if n.get('text'))


# --------------------------------------------------------------- narrative sanitising

_ALLOWED_TAGS = {
    'div', 'p', 'span', 'br', 'b', 'strong', 'i', 'em', 'u', 'sub', 'sup', 'pre',
    'ul', 'ol', 'li', 'dl', 'dt', 'dd', 'table', 'thead', 'tbody', 'tfoot', 'tr',
    'th', 'td', 'caption', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'blockquote',
}
_ALLOWED_ATTRS = {'colspan', 'rowspan'}
_VOID_TAGS = {'br', 'hr'}
_DROP_CONTENT = {'script', 'style', 'iframe', 'object', 'embed', 'head', 'title'}


class _Sanitiser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _DROP_CONTENT:
            self._skip += 1
            return
        if self._skip or tag not in _ALLOWED_TAGS:
            return
        kept = ''.join(f' {k}="{escape(v or "")}"' for k, v in attrs if k in _ALLOWED_ATTRS)
        self.out.append(f'<{tag}{kept}>')

    def handle_startendtag(self, tag, attrs):
        if tag in _VOID_TAGS and not self._skip:
            self.out.append(f'<{tag}>')

    def handle_endtag(self, tag):
        if tag in _DROP_CONTENT:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip or tag not in _ALLOWED_TAGS or tag in _VOID_TAGS:
            return
        self.out.append(f'</{tag}>')

    def handle_data(self, data):
        if not self._skip:
            self.out.append(escape(data))


def sanitise_narrative(div):
    """Reduce FHIR narrative XHTML to a safe subset of formatting tags (no attributes, links or scripts)."""
    if not div:
        return ''
    parser = _Sanitiser()
    parser.feed(div)
    parser.close()
    return ''.join(parser.out)


# ------------------------------------------------------------------- bundle resolver

class _Resolver:
    def __init__(self, bundle):
        self.by_ref = {}
        for entry in bundle.get('entry', []):
            res = entry.get('resource') or {}
            if entry.get('fullUrl'):
                self.by_ref[entry['fullUrl']] = res
            if res.get('resourceType') and res.get('id'):
                rel = f"{res['resourceType']}/{res['id']}"
                self.by_ref.setdefault(rel, res)
                # absolute fullUrl like http://server/fhir/Patient/1 -> also index Patient/1
        for key in list(self.by_ref):
            if '://' in key:
                parts = key.rstrip('/').split('/')
                if len(parts) >= 2:
                    self.by_ref.setdefault(f'{parts[-2]}/{parts[-1]}', self.by_ref[key])

    def resolve(self, ref, container=None):
        if not ref:
            return None
        target = ref.get('reference', '') if isinstance(ref, dict) else ref
        if not target:
            return None
        if target.startswith('#') and container:
            return next((c for c in container.get('contained', []) if c.get('id') == target[1:]), None)
        if target in self.by_ref:
            return self.by_ref[target]
        # absolute -> relative
        parts = target.rstrip('/').split('/')
        if len(parts) >= 2:
            return self.by_ref.get(f'{parts[-2]}/{parts[-1]}')
        return None

    def display(self, ref, container=None):
        """Display string for a Reference: resolve it and name the target, else use Reference.display."""
        if not ref:
            return ''
        res = self.resolve(ref, container)
        name = describe_party(res, self) if res else ''
        return name or ref.get('display', '') or ''


def describe_party(res, resolver):
    """One-line description of a Patient/Practitioner/PractitionerRole/Organization/Device/RelatedPerson."""
    rt = res.get('resourceType')
    if rt in ('Patient', 'Practitioner', 'RelatedPerson'):
        name = human_name(res.get('name'))
        if rt == 'RelatedPerson':
            rel = ccs_text(res.get('relationship'))
            return f'{name} ({rel})' if rel else name
        return name
    if rt == 'Organization':
        return res.get('name', '')
    if rt == 'PractitionerRole':
        who = resolver.display(res.get('practitioner'))
        role = ccs_text(res.get('code')) or ccs_text(res.get('specialty'))
        org = resolver.display(res.get('organization'))
        bits = [b for b in (who, role) if b]
        text = ', '.join(bits)
        return f'{text} – {org}' if org else text
    if rt == 'Device':
        names = [d.get('name') for d in res.get('deviceName', []) if d.get('name')]
        return (names[0] if names else '') or cc_text(res.get('type')) or res.get('manufacturer', '')
    return ''


# ------------------------------------------------------------------ row builders

def _medication_name(res, resolver):
    if res.get('medicationCodeableConcept'):
        return cc_text(res['medicationCodeableConcept'], 'Unknown medicine')
    ref = res.get('medicationReference')
    if ref:
        med = resolver.resolve(ref, res)
        if med:
            name = cc_text(med.get('code'))
            strength = ''
            ingredients = med.get('ingredient') or []
            if ingredients and not name:
                name = ', '.join(cc_text(i.get('itemCodeableConcept')) for i in ingredients if i.get('itemCodeableConcept'))
            form = cc_text(med.get('form'))
            if form and name and form.lower() not in name.lower():
                strength = f' ({form})'
            if name:
                return name + strength
        if ref.get('display'):
            return ref['display']
    return 'Unknown medicine'


def _dosage(res):
    dosages = res.get('dosage') or res.get('dosageInstruction') or []
    return '; '.join(d.get('text', '') for d in dosages if d.get('text'))


def _observation_value(res):
    value = fmt_choice(res, 'value')
    if value:
        return value
    comps = res.get('component') or []
    # Blood pressure style: systolic/diastolic with the same unit
    if len(comps) == 2 and all(isinstance(c.get('valueQuantity', {}).get('value'), (int, float)) for c in comps):
        units = {c['valueQuantity'].get('unit') for c in comps}
        if len(units) == 1:
            v = [c['valueQuantity'].get('value') for c in comps]
            return f"{v[0]:g}/{v[1]:g} {units.pop() or ''}".strip()
    if comps:
        return '; '.join(f"{cc_text(c.get('code'))}: {fmt_choice(c, 'value') or cc_text(c.get('dataAbsentReason'))}"
                         for c in comps)
    if res.get('dataAbsentReason'):
        return cc_text(res['dataAbsentReason'])
    return ''


def _row(res, resolver):
    rt = res.get('resourceType')
    status = ''
    if rt == 'Condition':
        status = status_code(res.get('clinicalStatus'))
        return {
            'Problem': cc_text(res.get('code'), 'Unknown problem'),
            'Status': status,
            'Onset': fmt_choice(res, 'onset'),
            'Resolved': fmt_choice(res, 'abatement'),
            'Notes': ' '.join(t for t in (cc_text(res.get('severity')), notes_text(res)) if t),
            '_status': status,
        }
    if rt == 'AllergyIntolerance':
        reactions = []
        for r in res.get('reaction', []):
            m = ccs_text(r.get('manifestation'))
            if m and r.get('severity'):
                m = f"{m} ({r['severity']})"
            if m:
                reactions.append(m)
        status = status_code(res.get('clinicalStatus'))
        return {
            'Substance': cc_text(res.get('code'), 'Unknown substance'),
            'Reaction': '; '.join(reactions),
            'Criticality': res.get('criticality', ''),
            'Status': status,
            'Recorded': fmt_date(res.get('recordedDate')) or fmt_choice(res, 'onset'),
            '_status': status,
        }
    if rt in ('MedicationStatement', 'MedicationRequest'):
        status = res.get('status', '')
        date = (fmt_choice(res, 'effective') or fmt_date(res.get('dateAsserted'))
                or fmt_date(res.get('authoredOn')))
        return {'Medicine': _medication_name(res, resolver), 'Dosage': _dosage(res),
                'Status': status, 'Date': date, '_status': status}
    if rt == 'Immunization':
        status = res.get('status', '')
        dose = ', '.join(f"dose {p['doseNumberPositiveInt']}" for p in res.get('protocolApplied', [])
                         if p.get('doseNumberPositiveInt'))
        return {'Vaccine': cc_text(res.get('vaccineCode'), 'Unknown vaccine'),
                'Date': fmt_choice(res, 'occurrence'),
                'Status': status,
                'Notes': ' '.join(t for t in (dose, notes_text(res)) if t), '_status': status}
    if rt == 'Procedure':
        status = res.get('status', '')
        return {'Procedure': cc_text(res.get('code'), 'Unknown procedure'),
                'Date': fmt_choice(res, 'performed'), 'Status': status,
                'Reason': ccs_text(res.get('reasonCode')), '_status': status}
    if rt == 'Observation':
        return {'Observation': cc_text(res.get('code'), 'Unknown observation'),
                'Result': _observation_value(res),
                'Date': fmt_choice(res, 'effective') or fmt_date(res.get('issued')),
                'Interpretation': ccs_text(res.get('interpretation')),
                '_status': res.get('status', '')}
    if rt == 'DiagnosticReport':
        status = res.get('status', '')
        return {'Report': cc_text(res.get('code'), 'Report'), 'Conclusion': res.get('conclusion', ''),
                'Date': fmt_choice(res, 'effective') or fmt_date(res.get('issued')),
                'Status': status, '_status': status}
    if rt == 'Device':
        return {'Device': describe_party(res, resolver) or 'Device', 'Status': res.get('status', '')}
    if rt == 'DeviceUseStatement':
        device = resolver.resolve(res.get('device'), res)
        name = describe_party(device, resolver) if device else res.get('device', {}).get('display', '')
        return {'Device': name or 'Device', 'Status': res.get('status', ''), 'Date': fmt_choice(res, 'timing')}
    if rt == 'Flag':
        return {'Alert': cc_text(res.get('code')), 'Status': res.get('status', ''), 'Period': fmt_period(res.get('period'))}
    if rt == 'CarePlan':
        return {'Plan': res.get('title') or res.get('description') or ccs_text(res.get('category')),
                'Status': res.get('status', ''), 'Period': fmt_period(res.get('period'))}
    if rt == 'Consent':
        return {'Consent': ccs_text(res.get('category')) or cc_text(res.get('scope')),
                'Status': res.get('status', ''), 'Date': fmt_date(res.get('dateTime'))}
    if rt == 'ClinicalImpression':
        return {'Assessment': res.get('summary') or res.get('description') or cc_text(res.get('code')),
                'Status': res.get('status', ''), 'Date': fmt_choice(res, 'effective') or fmt_date(res.get('date'))}
    name = res.get('name') if isinstance(res.get('name'), str) else ''
    label = (cc_text(res.get('code')) or cc_text(res.get('type')) or res.get('title')
             or name or res.get('id', ''))
    return {'Item': label, 'Type': rt}


def _no_known_cc(res):
    rt = res.get('resourceType')
    if rt in ('MedicationStatement', 'MedicationRequest'):
        return res.get('medicationCodeableConcept')
    if rt == 'Immunization':
        return res.get('vaccineCode')
    return res.get('code')


# ------------------------------------------------------------------- main entry

def _section(sec, resolver, depth=0, comp=None):
    code = ''
    for coding in (sec.get('code') or {}).get('coding', []):
        if coding.get('system') == LOINC:
            code = coding.get('code', '')
            break
    label, icon, colour = SECTION_META.get(code, DEFAULT_META)
    title = sec.get('title') or label or cc_text(sec.get('code'), 'Section')
    # Standard heading for known sections; the document's own title is kept as a subtitle.
    heading = label or title
    subtitle = title if label and title.strip().lower() != label.lower() else ''

    groups = {}          # resourceType -> {'type', 'columns', 'rows'}
    no_known = []
    unresolved = []
    seen = set()

    def add(res, level=0):
        if id(res) in seen:      # e.g. a panel member also listed directly in the section
            return
        seen.add(id(res))
        rt = res.get('resourceType', 'Unknown')
        if is_no_known(_no_known_cc(res)):
            no_known.append(cc_text(_no_known_cc(res)))
            return
        group = groups.setdefault(rt, {'type': rt, 'columns': COLUMNS.get(rt, DEFAULT_COLUMNS), 'rows': []})
        row = _row(res, resolver)
        row['_level'] = level
        group['rows'].append(row)
        if rt == 'Observation':
            for member_ref in res.get('hasMember', []):
                member = resolver.resolve(member_ref, res)
                if member:
                    add(member, level + 1)
        if rt == 'DiagnosticReport':
            for result_ref in res.get('result', []):
                result = resolver.resolve(result_ref, res)
                if result:
                    add(result, level + 1)

    for ref in sec.get('entry', []):
        res = resolver.resolve(ref, comp)
        if res is None:
            unresolved.append(ref.get('reference') or ref.get('display') or '?')
            continue
        add(res)

    empty_reason = ''
    if sec.get('emptyReason'):
        er = sec['emptyReason']
        er_code = status_code(er)
        empty_reason = er.get('text') or EMPTY_REASON_TEXT.get(er_code) or cc_text(er) or er_code

    narrative = sanitise_narrative((sec.get('text') or {}).get('div', ''))
    has_rows = any(g['rows'] for g in groups.values())

    return {
        'code': code,
        'title': title,
        'heading': heading,
        'subtitle': subtitle,
        'icon': icon,
        'colour': colour,
        'count': sum(1 for g in groups.values() for r in g['rows'] if not r.get('_level')),
        'depth': depth,
        'groups': list(groups.values()),
        'no_known': no_known,
        'empty_reason': empty_reason,
        'narrative_html': narrative,
        # narrative is the content when nothing structured can be shown
        'narrative_primary': bool(narrative) and not has_rows and not no_known and not empty_reason,
        'unresolved': unresolved,
        'subsections': [_section(s, resolver, depth + 1, comp) for s in sec.get('section', [])],
    }


def _absent_reason(res, element):
    """data-absent-reason code on a primitive (``_date``) or a complex element (``author[0]``), else ''."""
    candidates = [res.get('_' + element)]
    value = res.get(element)
    if isinstance(value, list):
        candidates += value
    elif isinstance(value, dict):
        candidates += [value, value.get('_reference')]
    for c in candidates:
        for ext in (c or {}).get('extension', []) if isinstance(c, dict) else []:
            if ext.get('url', '').endswith('data-absent-reason'):
                return ext.get('valueCode', 'unknown')
    return ''


def parse_summary(bundle):
    """Build the AU PS view model from a document Bundle (or a Bundle wrapping one).

    Returns a dict with ``header``, ``patient``, ``sections`` and ``warnings``.
    Raises ValueError if no Composition can be found.
    """
    if not isinstance(bundle, dict) or bundle.get('resourceType') != 'Bundle':
        raise ValueError('Not a FHIR Bundle')

    # A searchset/collection containing a single document Bundle -> unwrap it.
    if bundle.get('type') != 'document':
        inner = [e.get('resource') for e in bundle.get('entry', [])
                 if (e.get('resource') or {}).get('resourceType') == 'Bundle']
        if inner:
            bundle = inner[0]

    entries = bundle.get('entry', [])
    comp = next((e['resource'] for e in entries
                 if (e.get('resource') or {}).get('resourceType') == 'Composition'), None)
    if comp is None:
        raise ValueError('Bundle has no Composition, so it is not a patient summary document')

    resolver = _Resolver(bundle)
    warnings = []
    if bundle.get('type') != 'document':
        warnings.append(f"Bundle.type is '{bundle.get('type')}', expected 'document'")
    if entries and (entries[0].get('resource') or {}).get('resourceType') != 'Composition':
        warnings.append('The Composition is not the first entry in the Bundle')

    for element in ('subject', 'date', 'title', 'author'):
        if _absent_reason(comp, element):
            warnings.append(f'Composition.{element} is absent ({_absent_reason(comp, element)})')

    authors = []
    for a in comp.get('author', []):
        name = resolver.display(a, comp)
        if not name:
            absent = [x.get('valueCode') for x in a.get('extension', [])
                      if x.get('url', '').endswith('data-absent-reason')]
            name = f'Not recorded ({absent[0]})' if absent else ''
        if name:
            authors.append(name)
    attesters = []
    for att in comp.get('attester', []):
        who = resolver.display(att.get('party'), comp) or 'Unknown'
        attesters.append(f"{who} ({att.get('mode', '')}{', ' + fmt_date(att['time']) if att.get('time') else ''})")

    header = {
        'title': comp.get('title') or cc_text(comp.get('type'), 'Patient Summary'),
        'date': format_fhir_date(comp.get('date'), 'DT') if comp.get('date') else '',
        'status': comp.get('status', ''),
        'authors': authors,
        'custodian': resolver.display(comp.get('custodian'), comp),
        'attesters': attesters,
        'event_period': fmt_period((comp.get('event') or [{}])[0].get('period')),
        'bundle_timestamp': format_fhir_date(bundle.get('timestamp'), 'DT') if bundle.get('timestamp') else '',
        'identifier': (bundle.get('identifier') or {}).get('value', ''),
    }

    patient_res = resolver.resolve(comp.get('subject'), comp) or {}
    if not patient_res:
        patients = [e['resource'] for e in entries if (e.get('resource') or {}).get('resourceType') == 'Patient']
        if len(patients) == 1:
            patient_res = patients[0]
            warnings.append('Composition.subject did not resolve; showing the only Patient in the Bundle')
    patient = {}
    if patient_res:
        ids = []
        for ident in patient_res.get('identifier', []):
            label = cc_text(ident.get('type')) or ident.get('system', '').rsplit('/', 1)[-1]
            if ident.get('value'):
                ids.append(f"{label}: {ident['value']}" if label else ident['value'])
        patient = {
            'name': human_name(patient_res.get('name')) or 'Unknown',
            'birth_date': patient_res.get('birthDate', ''),
            'gender': patient_res.get('gender', ''),
            'identifiers': ids,
        }
    else:
        warnings.append('Composition.subject could not be resolved to a Patient')

    sections = [_section(s, resolver, 0, comp) for s in comp.get('section', [])]
    for i, sec in enumerate(sections):
        sec['anchor'] = f'aups-section-{i}'
    return {'header': header, 'patient': patient, 'sections': sections, 'warnings': warnings}
