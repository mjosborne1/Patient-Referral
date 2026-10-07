# Tasks: HCPD Bulk Import

Tag: ① provider lookup. Each slice is built test-first (red, then green, then refactor).

## 1. Export request — ①

Backend
- [x] 1.1 `build_export_parameters(types, type_filters, since=None)`: profile-conformant Parameters; validation (allowed types, a filter for every type, no `_include`, `_since` is an instant)
- [x] 1.2 `scope_filters(preset, value, types)`: linked `_typeFilter`s for the geographic, service-type and organisation presets
- [x] 1.3 `scope_key(parameters)`: a stable hash of types plus filters (the sync-state key)

## 2. HCPD client and token — ①

- [x] 2.1 `TokenProvider`: client-credentials fetch and caching with expiry skew (injected clock)
- [x] 2.2 `HcpdExportClient.kickoff()`: POST `$export` with the required headers → status URL; OperationOutcome on 4xx
- [x] 2.3 `poll()` → InProgress(retry_after, progress) | Complete(manifest) | Failed(outcome) | Gone
- [x] 2.4 `download(url, requires_token)` → parsed NDJSON resources; `cancel(status_url)`

## 3. Reconciliation (pure) — ①

- [x] 3.1 `classify(resource)` → upsert | remove (suppressed; Organization only when `includeSelf`)
- [x] 3.2 `prepare_for_import(resource, source)`: drop server meta, keep profile, add the import tag and `meta.source`
- [x] 3.3 `import_batches(resources, size)`: dependency-ordered batch Bundles of PUTs
- [x] 3.4 `removal_identifiers(list_resource)` → (types, system, value) from the HCPD Export Response List

## 4. Referral-server importer — ①

- [x] 4.1 Apply batches; count each entry by type (upserted / failed)
- [x] 4.2 Delete suppressed records (tagged only) and resolve and delete List identifiers; refused deletes count as failed

## 5. Job runner and persistence — ①

- [x] 5.1 `JobStore` (atomic JSON files under `instance/hcpd/`), with one active job enforced
- [x] 5.2 `run_job(job)` state machine with an injected sleep/clock: poll honouring `max(Retry-After, 120)`, then download, import and complete
- [x] 5.3 Sync state: advance `transactionTime` per scope only after a fully applied import
- [x] 5.4 Background thread start; resume of an interrupted job; cancel

## 6. UI — ①

Backend
- [x] 6.1 Blueprint routes: `GET /directory/import`, `POST /directory/import` (kickoff), `GET /directory/import/jobs` (partial), `POST …/<job>/cancel`, `POST …/<job>/resume`, `POST /directory/import/incremental`

Frontend
- [x] 6.2 `directory_import.html`: types, preset, value, mode, advanced filters; config warning when OAuth isn't set
- [x] 6.3 The jobs partial polls every 5 s while a job is active; it shows status, progress, per-type counts and errors
- [x] 6.4 Sidebar link; smoke test of the page render

## 7. Docs and verification

- [x] 7.1 `.env.example`: HCPD_* keys
- [ ] 7.2 Live run against HCPD SIT (needs credentials); adjust presets and List handling to the observed behaviour; record findings in the design
