---
id: 05-aimap-codesearch-testname
type: proposal
status: draft
scenario-steps: ["① Placer creates request"]
created: 2026-06-25
---

# Proposal: ai-map Code Search for Test Name Field

## Problem

The **Test Name** typeahead in `diag_request.html` currently resolves `ServiceRequest.code`
via a ValueSet/$expand call to the public Ontoserver instance at
`https://r4.ontoserver.csiro.au/fhir`, using two placeholder "boosted" ValueSet URLs:

```
http://pathologyrequest.example.com.au/ValueSet/boosted   # pathology
http://radiologyrequest.example.com.au/ValueSet/boosted   # radiology
```

These URLs are illustrative only and do not resolve to real, curated value sets, so in practice
the typeahead returns no results. The ai-map project (`/Users/osb074/Development/aehrc/ai-map`)
already integrates a purpose-built **CodeSearch AI API** that maps natural-language text to
SNOMED CT codes with high precision. Reusing that API here would give the demo a live,
semantically-aware test name lookup without any UI changes.

## Proposed Change

### 1. New module — `codesearch.py`

Extract the auth and search logic from ai-map's `main.py` into a standalone module that reads
`CODESEARCH_*` credentials from `.env`:

| Env var | Purpose |
|---|---|
| `CODESEARCH_API_ENDPOINT` | POST endpoint for code search (e.g. `https://.../api/v1/find-code`) |
| `CODESEARCH_TOKEN_ENDPOINT` | OAuth2 token endpoint (client_credentials grant) |
| `CODESEARCH_CLIENT_ID` | OAuth2 client ID |
| `CODESEARCH_CLIENT_SECRET` | OAuth2 client secret |
| `CODESEARCH_CONTENT_TYPE` | Content-Type header override (default: `application/json`) |

Key functions:

```python
def get_token(force: bool = False) -> str:
    """Return a cached Bearer token; re-fetches when expired (5-min TTL or
    expires_in from token response, whichever is shorter)."""

def search_codes(text: str, context: str, top_n: int = 10) -> list[dict]:
    """POST {text, context, top_n} to CODESEARCH_API_ENDPOINT.
    Returns a list of {code, display, system} dicts from resp["matches"].
    Retries once with a fresh token on any HTTP error.
    Returns [] when CODESEARCH_API_ENDPOINT is not configured (graceful fallback).
    """
```

**Auth flow** (mirrors ai-map `main.py` exactly):

```
POST CODESEARCH_TOKEN_ENDPOINT
  Content-Type: application/x-www-form-urlencoded
  Body: grant_type=client_credentials&client_id=…&client_secret=…
→ {"access_token": "…", "expires_in": 300, …}
```

**Search call**:

```
POST CODESEARCH_API_ENDPOINT
  Authorization: Bearer <token>
  Content-Type: application/json          # or CODESEARCH_CONTENT_TYPE if set
  Body: {"text": "full blood count", "context": "…profile…#ServiceRequest.code", "top_n": 10}
→ {"matches": [{"code": "26604007", "display": "Full blood count", "system": "http://snomed.info/sct"}, …]}
```

### 2. Context strings per request category

The `context` field disambiguates the target element within the AU eRequesting IG:

| Request category | Context string |
|---|---|
| `pathology` | `http://hl7.org.au/fhir/ereq/StructureDefinition/au-erequesting-servicerequest-path#ServiceRequest.code` |
| `radiology` | `http://hl7.org.au/fhir/ereq/StructureDefinition/au-erequesting-servicerequest-imag#ServiceRequest.code` |

### 3. Update `GET /fhir/diagvalueset/expand` in `app.py`

Replace (not augment) the Ontoserver path with a call to `codesearch.search_codes()`:

```python
from codesearch import search_codes as cs_search

CODESEARCH_CONTEXT = {
    'pathology': 'http://hl7.org.au/fhir/ereq/StructureDefinition/'
                 'au-erequesting-servicerequest-path#ServiceRequest.code',
    'radiology': 'http://hl7.org.au/fhir/ereq/StructureDefinition/'
                 'au-erequesting-servicerequest-imag#ServiceRequest.code',
}

@app.route('/fhir/diagvalueset/expand')
def diag_valueset_expand():
    request_cat = request.args.get('requestCategory', '').lower()
    query = request.args.get('testName', '').strip()
    if not request_cat or not query or request_cat not in CODESEARCH_CONTEXT:
        return render_template('partials/test_names.html', testNames=[])
    context = CODESEARCH_CONTEXT[request_cat]
    matches = cs_search(query, context, top_n=10)
    testNames = [{"code": m["code"], "display": m.get("display") or m["code"]}
                 for m in matches if m.get("code")]
    return render_template('partials/test_names.html', testNames=testNames)
```

No changes to `diag_request.html`, `test_names.html`, or any other template — the existing
HTMX wiring, dropdown, and tag-selection logic are unchanged.

### 4. Graceful degradation

When `CODESEARCH_API_ENDPOINT` is not set, `search_codes()` returns `[]` immediately and
the typeahead renders an empty dropdown (same behaviour as the current broken Ontoserver path).
No error is surfaced to the user. A `WARNING` is emitted to the Flask log on first call so
operators can detect misconfiguration.

## Non-goals

- No changes to the referral form (`referral_form.html`) — the Test Name field is in
  the **diagnostic request** form only.
- No feedback loop to the CodeSearch API (POST `/api/v1/feedback`) in this iteration;
  that can be added in a follow-up once a confirmed-selection UX exists.
- No changes to the reason/indication lookup (`GET /fhir/reasonvalueset/expand`) in this
  proposal — that can be tackled separately.
- No caching layer beyond the in-process token TTL; the CodeSearch API is assumed fast enough
  for typeahead latency (<200 ms).

## FHIR Profiles Touched

- `au-erequesting-servicerequest-path` — `ServiceRequest.code` (pathology)
- `au-erequesting-servicerequest-imag` — `ServiceRequest.code` (radiology)

## Files Impacted

| File | Change |
|---|---|
| `codesearch.py` | **New** — auth + search client |
| `app.py` | Update `diag_valueset_expand()` to use `codesearch.search_codes()` |
| `.env.example` | Already updated — `CODESEARCH_*` keys present |
| `tests/test_codesearch.py` | **New** — unit tests with mocked HTTP |

## Open Questions

1. **Context strings** — the values above match the AU eRequesting IG 1.0 profile URLs.
   Confirm the CodeSearch service was trained against these exact URLs.
2. **`top_n`** — 10 results feels right for a typeahead; adjust based on observed API latency.
3. **`CODESEARCH_CONTENT_TYPE`** — the env var is present but ai-map always hardcodes
   `application/json`. Clarify whether any CodeSearch API variant requires a different
   content type before honouring this override.
