"""
Import providers from the Health Connect Provider Directory (HCPD) bulk export.

Pure builders for the HCPD Export Request Parameters and for reconciling exported resources
with the referral FHIR server, plus the HCPD client, importer and background job runner.
See openspec/changes/add-hcpd-bulk-import/design.md.
"""
import base64
import hashlib
import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

EXPORT_PARAMETERS_PROFILE = (
    "http://digitalhealth.gov.au/fhir/hcpd/StructureDefinition/hcpd-export-request-parameters")
NDJSON = "application/fhir+ndjson"
EXPORTABLE_TYPES = ("Organization", "Location", "HealthcareService", "Practitioner",
                    "PractitionerRole", "Endpoint", "Provenance")

_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


class ExportRequestError(ValueError):
    """The export request would be rejected by HCPD."""


def _filter_type(type_filter):
    resource_type, sep, _ = type_filter.partition("?")
    if not sep or not re.fullmatch(r"[A-Z][A-Za-z]+", resource_type):
        raise ExportRequestError(f"_typeFilter must start with a resource type: {type_filter!r}")
    return resource_type


def build_export_parameters(types, type_filters, since=None):
    """HCPD Export Request Parameters for the given types and one _typeFilter entry per filter."""
    if not types:
        raise ExportRequestError("Choose at least one resource type to export")
    for resource_type in types:
        if resource_type not in EXPORTABLE_TYPES:
            raise ExportRequestError(f"{resource_type} is not exportable from HCPD")
    filtered = set()
    for type_filter in type_filters:
        resource_type = _filter_type(type_filter)
        if resource_type not in types:
            raise ExportRequestError(f"{resource_type} is not in _type but has a _typeFilter")
        if re.search(r"[?&]_(rev)?include", type_filter):
            raise ExportRequestError(f"_include/_revinclude is not allowed in _typeFilter: {type_filter!r}")
        filtered.add(resource_type)
    for resource_type in types:
        if resource_type not in filtered:
            raise ExportRequestError(f"{resource_type} has no _typeFilter")
    if since is not None and not _INSTANT.match(since):
        raise ExportRequestError(f"_since must be an instant with time and timezone: {since!r}")

    parameters = [{"name": "_outputFormat", "valueString": NDJSON},
                  {"name": "_type", "valueString": ",".join(types)}]
    parameters += [{"name": "_typeFilter", "valueString": f} for f in type_filters]
    if since is not None:
        parameters.append({"name": "_since", "valueInstant": since})
    return {"resourceType": "Parameters", "meta": {"profile": [EXPORT_PARAMETERS_PROFILE]},
            "parameter": parameters}


def scope_key(parameters):
    """Stable key for an export's scope (types and filters), independent of _since and order."""
    types, filters = set(), []
    for p in parameters["parameter"]:
        if p["name"] == "_type":
            types.update(t.strip() for t in p["valueString"].split(","))
        elif p["name"] == "_typeFilter":
            filters.append(p["valueString"])
    canonical = json.dumps({"types": sorted(types), "filters": sorted(filters)})
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


# Linked _typeFilter templates per scope preset; {v} is the preset value. Order follows `types`.
_PRESET_FILTERS = {
    "geographic": {
        "Organization": "Organization?_has:Location:organization:address-state={v}",
        "Location": "Location?address-state={v}",
        "HealthcareService": "HealthcareService?location.address-state={v}",
        "PractitionerRole": "PractitionerRole?location.address-state={v}",
        "Practitioner": "Practitioner?_has:PractitionerRole:practitioner:location.address-state={v}",
        "Endpoint": "Endpoint?_has:PractitionerRole:endpoint:location.address-state={v}",
    },
    "service-type": {
        "Organization": "Organization?_has:HealthcareService:organization:service-type={v}",
        "Location": "Location?_has:HealthcareService:location:service-type={v}",
        "HealthcareService": "HealthcareService?service-type={v}",
        "PractitionerRole": "PractitionerRole?service.service-type={v}",
        "Practitioner": "Practitioner?_has:PractitionerRole:practitioner:service.service-type={v}",
        "Endpoint": "Endpoint?_has:HealthcareService:endpoint:service-type={v}",
    },
    "organisation": {
        "Organization": "Organization?{org}={v}",
        "Location": "Location?organization.{org}={v}",
        "HealthcareService": "HealthcareService?organization.{org}={v}",
        "PractitionerRole": "PractitionerRole?organization.{org}={v}",
        "Practitioner": "Practitioner?_has:PractitionerRole:practitioner:organization.{org}={v}",
        "Endpoint": "Endpoint?organization.{org}={v}",
    },
}
# Narrowing a service-type scope to a state, for the types that carry a location.
_STATE_SUFFIX = {"HealthcareService": "&location.address-state={s}",
                 "PractitionerRole": "&location.address-state={s}"}


def scope_filters(preset, value, types, state=None):
    """Linked _typeFilters (one per type) constraining every type by the same preset criterion."""
    templates = _PRESET_FILTERS.get(preset)
    if templates is None:
        raise ExportRequestError(f"Unknown scope preset {preset!r}")
    value = (value or "").strip()
    if not value:
        raise ExportRequestError(f"The {preset} scope needs a value")
    org_param = "identifier" if "|" in value else "name"
    filters = []
    for resource_type in types:
        if resource_type not in templates:
            raise ExportRequestError(f"{resource_type} is not supported by the {preset} scope")
        type_filter = templates[resource_type].format(v=value, org=org_param)
        if preset == "service-type" and state and resource_type in _STATE_SUFFIX:
            type_filter += _STATE_SUFFIX[resource_type].format(s=state)
        filters.append(type_filter)
    return filters


# ── Reconciliation (pure) ────────────────────────────────────────────────────

SUPPRESSED_EXTENSION = "http://digitalhealth.gov.au/fhir/cc/StructureDefinition/suppressed"
IMPORT_TAG = {"system": "http://aehrc.csiro.au/fhir/patient-referral/tag", "code": "hcpd-import",
              "display": "Imported from HCPD bulk export"}
# Referenced types first, so servers that enforce referential integrity accept each batch.
IMPORT_ORDER = ("Organization", "Location", "HealthcareService", "Practitioner",
                "PractitionerRole", "Endpoint")
HPIO = "http://ns.electronichealth.net.au/id/hi/hpio/1.0"
HSPO = "http://ns.electronichealth.net.au/id/hi/hspo/1.0"
HPII = "http://ns.electronichealth.net.au/id/hi/hpii/1.0"
HCPD_LOCAL = "http://digitalhealth.gov.au/fhir/hcpd/id/hcpd-local-identifier"
REMOVAL_TYPES_BY_SYSTEM = {
    HPIO: ("Organization",),
    HSPO: ("Organization",),
    HPII: ("Practitioner",),
    HCPD_LOCAL: ("Location", "HealthcareService", "PractitionerRole", "Endpoint"),
}


def _suppression(resource):
    return next((e for e in resource.get("extension", []) if e.get("url") == SUPPRESSED_EXTENSION),
                None)


def classify(resource):
    """What to do locally with an exported resource: upsert | remove | removal-list | skip."""
    resource_type = resource.get("resourceType")
    if resource_type == "List":
        return "removal-list"
    if resource_type not in IMPORT_ORDER:
        return "skip"
    suppression = _suppression(resource)
    if suppression is None:
        return "upsert"
    if resource_type == "Organization":
        include_self = next((e.get("valueBoolean") for e in suppression.get("extension", [])
                             if e.get("url") == "includeSelf"), False)
        return "remove" if include_self else "upsert"
    return "remove"


def prepare_for_import(resource, source):
    """Copy for PUT to the referral server: server meta dropped, profile kept, import-tagged."""
    meta = resource.get("meta", {})
    prepared_meta = {}
    if meta.get("profile"):
        prepared_meta["profile"] = meta["profile"]
    prepared_meta["tag"] = [t for t in meta.get("tag", []) if t.get("code") != IMPORT_TAG["code"]
                            or t.get("system") != IMPORT_TAG["system"]] + [IMPORT_TAG]
    prepared_meta["source"] = source
    return {**{k: v for k, v in resource.items() if k != "meta"}, "meta": prepared_meta}


def import_batches(resources, source, size=100):
    """[(type, batch Bundle)] of PUT-by-id entries, grouped by type in dependency order."""
    batches = []
    for resource_type in IMPORT_ORDER:
        of_type = [r for r in resources if r.get("resourceType") == resource_type]
        for start in range(0, len(of_type), size):
            batches.append((resource_type, {"resourceType": "Bundle", "type": "batch", "entry": [
                {"resource": prepare_for_import(r, source),
                 "request": {"method": "PUT", "url": f"{resource_type}/{r['id']}"}}
                for r in of_type[start:start + size]]}))
    return batches


def removal_identifiers(hcpd_list):
    """[(candidate types, system, value)] for each recognised identifier on an HCPD removal List."""
    removals = []
    for entry in hcpd_list.get("entry", []):
        identifier = entry.get("item", {}).get("identifier", {})
        types = REMOVAL_TYPES_BY_SYSTEM.get(identifier.get("system"))
        if types and identifier.get("value"):
            removals.append((types, identifier["system"], identifier["value"]))
    return removals


# ── HCPD HTTP ────────────────────────────────────────────────────────────────

class TokenProvider:
    """OAuth 2.0 client-credentials access token, cached until shortly before it expires."""

    EXPIRY_SKEW_SECONDS = 60

    def __init__(self, token_endpoint, client_id, client_secret, *, scope=None, clock=time.time,
                 timeout=30):
        self.token_endpoint = token_endpoint
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope
        self.clock = clock
        self.timeout = timeout
        self._token = None
        self._expires_at = 0.0

    def __call__(self):
        if not self.token_endpoint:
            return None
        if self._token and self.clock() < self._expires_at - self.EXPIRY_SKEW_SECONDS:
            return self._token
        form = {"grant_type": "client_credentials", "client_id": self.client_id,
                "client_secret": self.client_secret}
        if self.scope:
            form["scope"] = self.scope
        response = requests.post(self.token_endpoint, data=form, timeout=self.timeout)
        response.raise_for_status()
        body = response.json()
        self._token = body["access_token"]
        self._expires_at = self.clock() + int(body.get("expires_in", 300))
        return self._token


class StaticToken:
    """A pre-issued bearer token (e.g. the long-lived JWTs HCPD SIT hands out for connectathons)."""

    def __init__(self, token):
        self.token = (token or "").strip() or None

    def __call__(self):
        return self.token


def token_from_env():
    """OAuth client credentials if HCPD_TOKEN_ENDPOINT is set, else HCPD_BEARER_TOKEN(_FILE)."""
    if os.environ.get("HCPD_TOKEN_ENDPOINT"):
        return TokenProvider(os.environ["HCPD_TOKEN_ENDPOINT"], os.environ.get("HCPD_CLIENT_ID"),
                             os.environ.get("HCPD_CLIENT_SECRET"), scope=os.environ.get("HCPD_SCOPE"))
    token = os.environ.get("HCPD_BEARER_TOKEN")
    token_file = os.environ.get("HCPD_BEARER_TOKEN_FILE")
    if not token and token_file and Path(token_file).is_file():
        token = Path(token_file).read_text()
    return StaticToken(token)


def jwt_expiry(token):
    """The `exp` claim (epoch seconds) of a JWT, read without verification; None if absent."""
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return int(claims["exp"]) if "exp" in claims else None
    except (IndexError, ValueError, TypeError, AttributeError):
        return None


def _operation_outcome(response):
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and body.get("resourceType") == "OperationOutcome":
        return body
    return {"resourceType": "OperationOutcome", "issue": [{
        "severity": "error", "code": "exception",
        "diagnostics": f"HTTP {response.status_code}: {response.text[:500]}"}]}


class HcpdError(Exception):
    """An HCPD request failed; carries the server's (or a synthesised) OperationOutcome."""

    def __init__(self, response):
        self.status_code = response.status_code
        self.operation_outcome = _operation_outcome(response)
        issue = (self.operation_outcome.get("issue") or [{}])[0]
        super().__init__(f"HTTP {response.status_code}: {issue.get('diagnostics', '')}")


@dataclass
class ExportStatus:
    state: str  # in-progress | complete | failed | gone
    retry_after: int | None = None
    progress: str | None = None
    manifest: dict | None = None
    operation_outcome: dict | None = None


class HcpdExportClient:
    """HCPD Bulk Data $export: kickoff, status polling, output download and cancellation."""

    # Azure Application Gateway in front of HCPD blocks the default python-requests User-Agent.
    USER_AGENT = "Mozilla/5.0 (compatible; PatientReferralApp/1.0)"

    def __init__(self, base_url, token=lambda: None, timeout=60):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _headers(self, accept, with_token=True):
        headers = {"Accept": accept, "X-Request-ID": str(uuid.uuid4()),
                   "User-Agent": self.USER_AGENT}
        token = self.token() if with_token else None
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def kickoff(self, parameters):
        """Start an export; returns the absolute status URL from Content-Location."""
        headers = self._headers("application/fhir+json")
        headers.update({"Content-Type": "application/fhir+json", "Prefer": "respond-async"})
        response = requests.post(f"{self.base_url}/$export", data=json.dumps(parameters),
                                 headers=headers, timeout=self.timeout)
        if response.status_code != 202 or "Content-Location" not in response.headers:
            raise HcpdError(response)
        return response.headers["Content-Location"]

    def poll(self, status_url):
        response = requests.get(status_url, headers=self._headers("application/json"),
                                timeout=self.timeout)
        if response.status_code == 202:
            retry_after = response.headers.get("Retry-After")
            return ExportStatus("in-progress",
                                retry_after=int(retry_after) if retry_after and retry_after.isdigit() else None,
                                progress=response.headers.get("X-Progress"))
        if response.status_code == 200:
            return ExportStatus("complete", manifest=response.json())
        if response.status_code == 404:
            return ExportStatus("gone", operation_outcome=_operation_outcome(response))
        return ExportStatus("failed", operation_outcome=_operation_outcome(response))

    def download(self, url, *, requires_token):
        """The resources in one NDJSON output file."""
        response = requests.get(url, headers=self._headers(NDJSON, with_token=requires_token),
                                timeout=self.timeout)
        if not response.ok:
            raise HcpdError(response)
        return [json.loads(line) for line in response.text.splitlines() if line.strip()]

    def cancel(self, status_url):
        response = requests.delete(status_url, headers=self._headers("application/fhir+json"),
                                   timeout=self.timeout)
        if response.status_code not in (200, 202, 204, 404):
            raise HcpdError(response)


# ── Referral server import ──────────────────────────────────────────────────

MAX_REPORTED_ERRORS = 50


@dataclass
class ImportCounts:
    by_type: dict = field(default_factory=dict)  # type -> {"upserted", "removed", "failed"}
    errors: list = field(default_factory=list)

    def add(self, resource_type, outcome, error=None):
        counts = self.by_type.setdefault(resource_type, {"upserted": 0, "removed": 0, "failed": 0})
        counts[outcome] += 1
        if error and len(self.errors) < MAX_REPORTED_ERRORS:
            self.errors.append(error)

    def merge(self, other):
        for resource_type, counts in other.by_type.items():
            mine = self.by_type.setdefault(resource_type, {"upserted": 0, "removed": 0, "failed": 0})
            for key, value in counts.items():
                mine[key] += value
        self.errors.extend(other.errors[:MAX_REPORTED_ERRORS - len(self.errors)])

    @property
    def failed(self):
        return sum(c["failed"] for c in self.by_type.values())


def _diagnostics(outcome):
    issues = (outcome or {}).get("issue") or [{}]
    return issues[0].get("diagnostics") or issues[0].get("details", {}).get("text") or "error"


def _is_import_tagged(resource):
    return any(t.get("system") == IMPORT_TAG["system"] and t.get("code") == IMPORT_TAG["code"]
               for t in resource.get("meta", {}).get("tag", []))


class ReferralImporter:
    """Upserts exported directory resources into the referral server and applies removals."""

    def __init__(self, base_url, auth=None, bearer=None, verify=True, batch_size=100, timeout=120):
        self.base_url = base_url.rstrip("/")
        self.auth = None if bearer else auth
        self.headers = {"Accept": "application/fhir+json", "Content-Type": "application/fhir+json"}
        if bearer:
            self.headers["Authorization"] = f"Bearer {bearer}"
        self.verify = verify
        self.batch_size = batch_size
        self.timeout = timeout

    def _request(self, method, path="", **kwargs):
        url = f"{self.base_url}/{path}" if path else self.base_url
        return requests.request(method, url, auth=self.auth, headers=self.headers,
                                verify=self.verify, timeout=self.timeout, **kwargs)

    def apply(self, resources, *, source):
        """Apply one export file's resources; returns per-type counts and errors."""
        counts = ImportCounts()
        upserts, removals, lists = [], [], []
        for resource in resources:
            action = classify(resource)
            {"upsert": upserts, "remove": removals, "removal-list": lists}.get(
                action, []).append(resource)
        for resource_type, batch in import_batches(upserts, source, self.batch_size):
            self._apply_batch(resource_type, batch, counts)
        for resource in removals:
            self._remove(resource["resourceType"], resource["id"], counts)
        for hcpd_list in lists:
            for types, system, value in removal_identifiers(hcpd_list):
                self._remove_by_identifier(types, system, value, counts)
        return counts

    def _apply_batch(self, resource_type, batch, counts):
        response = self._request("POST", data=json.dumps(batch))
        refs = [e["request"]["url"] for e in batch["entry"]]
        if not response.ok:
            message = _diagnostics(_operation_outcome(response))
            for ref in refs:
                counts.add(resource_type, "failed", f"{ref}: {message}")
            return
        results = response.json().get("entry", [])
        for ref, result in zip(refs, results + [{}] * (len(refs) - len(results))):
            status = result.get("response", {}).get("status", "")
            if status.startswith("2"):
                counts.add(resource_type, "upserted")
            else:
                counts.add(resource_type, "failed",
                           f"{ref}: {_diagnostics(result.get('response', {}).get('outcome'))}")

    def _delete(self, resource_type, resource_id, counts):
        response = self._request("DELETE", f"{resource_type}/{resource_id}")
        if response.ok:
            counts.add(resource_type, "removed")
        else:
            counts.add(resource_type, "failed",
                       f"{resource_type}/{resource_id}: {_diagnostics(_operation_outcome(response))}")

    def _remove(self, resource_type, resource_id, counts):
        response = self._request("GET", f"{resource_type}/{resource_id}")
        if response.status_code in (404, 410):
            return  # never imported, or already gone
        if not response.ok:
            counts.add(resource_type, "failed",
                       f"{resource_type}/{resource_id}: {_diagnostics(_operation_outcome(response))}")
            return
        if _is_import_tagged(response.json()):
            self._delete(resource_type, resource_id, counts)

    def _remove_by_identifier(self, types, system, value, counts):
        tag = f"{IMPORT_TAG['system']}|{IMPORT_TAG['code']}"
        for resource_type in types:
            response = self._request("GET", resource_type,
                                     params={"identifier": f"{system}|{value}", "_tag": tag})
            if not response.ok:
                counts.add(resource_type, "failed",
                           f"{resource_type}?identifier={system}|{value}: "
                           f"{_diagnostics(_operation_outcome(response))}")
                continue
            for entry in response.json().get("entry", []):
                resource = entry.get("resource", {})
                if resource.get("resourceType") == resource_type:
                    self._delete(resource_type, resource["id"], counts)


# ── Jobs ─────────────────────────────────────────────────────────────────────

ACTIVE_STATUSES = {"submitted", "polling", "downloading", "importing", "cancelling"}


class JobAlreadyActive(Exception):
    """Another export is still running; HCPD advises one export at a time per dataset."""


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobStore:
    """Export jobs and per-scope sync points as JSON files (atomic writes) under a directory."""

    def __init__(self, root):
        self.root = Path(root)
        self.jobs_dir = self.root / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _write(self, path, data):
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        os.replace(tmp, path)

    def create(self, job):
        with self._lock:
            if self.active():
                raise JobAlreadyActive("An HCPD export is already running")
            created = {"id": uuid.uuid4().hex[:12], "seq": time.time_ns(), "status": "submitted",
                       "created": _now_iso(),
                       "counts": {"by_type": {}, "errors": []}, **job}
            created["updated"] = created["created"]
            self._write(self.jobs_dir / f"{created['id']}.json", created)
            return created

    def save(self, job):
        job = {**job, "updated": _now_iso()}
        self._write(self.jobs_dir / f"{job['id']}.json", job)
        return job

    def get(self, job_id):
        path = self.jobs_dir / f"{job_id}.json"
        if not re.fullmatch(r"[0-9a-f]{12}", job_id) or not path.exists():
            return None
        return json.loads(path.read_text())

    def list(self):
        jobs = [json.loads(p.read_text()) for p in self.jobs_dir.glob("*.json")]
        return sorted(jobs, key=lambda j: j.get("seq", 0), reverse=True)

    def active(self):
        return next((j for j in self.list() if j["status"] in ACTIVE_STATUSES), None)

    def _sync(self):
        path = self.root / "sync.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def get_since(self, key):
        return self._sync().get(key)

    def set_since(self, key, transaction_time):
        with self._lock:
            sync = self._sync()
            sync[key] = transaction_time
            self._write(self.root / "sync.json", sync)


MIN_POLL_SECONDS = 120  # HCPD rate-limits status polling to one request per 120 s
_WAIT_STEP_SECONDS = 5  # how often a waiting job checks for a cancel request


def _fail(store, job, message):
    return store.save({**store.get(job["id"]), "status": "failed", "error": message})


def _wait(store, job_id, seconds, sleep):
    """Sleep up to `seconds`, returning False early if the job was asked to cancel."""
    remaining = seconds
    while remaining > 0:
        step = min(_WAIT_STEP_SECONDS, remaining)
        sleep(step)
        remaining -= step
        if store.get(job_id)["status"] == "cancelling":
            return False
    return True


def run_job(job_id, store, hcpd, importer, *, source, sleep=time.sleep, clock=time.time):
    """Drive one export job to completion: kickoff, poll, download, import, advance sync point."""
    job = store.get(job_id)
    try:
        if not job.get("status_url"):
            job = store.save({**job, "status_url": hcpd.kickoff(job["parameters"]),
                              "status": "polling"})
        manifest = job.get("manifest")
        while manifest is None:
            job = store.get(job_id)
            if job["status"] == "cancelling":
                hcpd.cancel(job["status_url"])
                return store.save({**job, "status": "cancelled"})
            status = hcpd.poll(job["status_url"])
            if status.state == "complete":
                manifest = status.manifest
                break
            if status.state in ("failed", "gone"):
                return _fail(store, job, _diagnostics(status.operation_outcome))
            wait = max(status.retry_after or 0, MIN_POLL_SECONDS)
            store.save({**job, "status": "polling", "progress": status.progress,
                        "next_poll_at": clock() + wait})
            if not _wait(store, job_id, wait, sleep):
                continue  # cancel requested; handled at the top of the loop
        return _import(store, store.get(job_id), manifest, hcpd, importer, source)
    except (HcpdError, requests.RequestException, ValueError, KeyError) as error:
        return _fail(store, job, str(error))


def _import(store, job, manifest, hcpd, importer, source):
    job = store.save({**job, "status": "downloading", "manifest": manifest,
                      "message": manifest.get("message")})
    counts = ImportCounts()
    outputs = manifest.get("output", [])
    for number, output in enumerate(outputs, start=1):
        store.save({**job, "status": "importing",
                    "progress": f"File {number} of {len(outputs)} ({output.get('type')})",
                    "counts": {"by_type": counts.by_type, "errors": counts.errors}})
        resources = hcpd.download(output["url"], requires_token=manifest.get("requiresAccessToken", True))
        counts.merge(importer.apply(resources, source=source))
    export_errors = manifest.get("error") or []
    clean = counts.failed == 0 and not export_errors
    if clean and manifest.get("transactionTime"):
        # Only a fully applied export may move the incremental sync point (HCPD export guidance).
        store.set_since(job["scope_key"], manifest["transactionTime"])
    return store.save({**store.get(job["id"]), "status": "complete" if clean else "complete-with-errors",
                       "progress": None, "counts": {"by_type": counts.by_type, "errors": counts.errors},
                       "export_errors": export_errors})


def _start_daemon_thread(target):
    thread = threading.Thread(target=target, name="hcpd-export", daemon=True)
    thread.start()
    return thread


class JobRunner:
    """Runs export jobs on a background thread; at most one at a time per app instance."""

    def __init__(self, store, *, hcpd_factory, start_thread=_start_daemon_thread,
                 sleep=time.sleep, clock=time.time):
        self.store = store
        self.hcpd_factory = hcpd_factory
        self.start_thread = start_thread
        self.sleep = sleep
        self.clock = clock
        self._running = set()  # job ids with a live thread in this process
        self._lock = threading.Lock()

    def _launch(self, job_id, importer, source):
        def target():
            try:
                run_job(job_id, self.store, self.hcpd_factory(), importer, source=source,
                        sleep=self.sleep, clock=self.clock)
            finally:
                with self._lock:
                    self._running.discard(job_id)
        with self._lock:
            self._running.add(job_id)
        self.start_thread(target)

    def start(self, parameters, *, mode, importer, source):
        """Create and start a job. The importer carries the referral-server credentials in memory."""
        job = self.store.create({"mode": mode, "parameters": parameters,
                                 "scope_key": scope_key(parameters)})
        self._launch(job["id"], importer, source)
        return job

    def is_interrupted(self, job):
        """Active on disk but with no thread in this process (e.g. the app restarted)."""
        return job["status"] in ACTIVE_STATUSES and job["id"] not in self._running

    def resume(self, job_id, *, importer, source):
        job = self.store.get(job_id)
        if job and self.is_interrupted(job):
            self._launch(job_id, importer, source)

    def cancel(self, job_id):
        job = self.store.get(job_id)
        if not job or job["status"] not in ACTIVE_STATUSES:
            return
        if job_id in self._running:
            self.store.save({**job, "status": "cancelling"})
            return
        if job.get("status_url"):
            self.hcpd_factory().cancel(job["status_url"])
        self.store.save({**job, "status": "cancelled"})
