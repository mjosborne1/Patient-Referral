---
id: 04-filler-specialist-view
type: proposal
status: draft
scenario-steps: ["③GET filler", "④PUT Task status"]
created: 2026-06-17
---

# Proposal: Filler / Specialist View

## Problem

Scenario 1 requires a **Filler** actor (the specialist / receiving system) that can:
- Retrieve incoming referrals from the AU eRequesting FHIR server (step ③)
- Update the Task status to reflect acceptance, in-progress, and completion (step ④)

Without this, the demo is one-sided — participants can only see the Placer submitting a referral
but cannot observe the status lifecycle that the Placer and Patient then monitor (steps ⑤ and ⑥).
Adding a Filler view makes the full round-trip demonstrable within a single app instance.

## Proposed Change

Add a **Filler Dashboard** at `GET /filler` that:

1. Lists all `Task` resources on the configured FHIR server with status in
   `{requested, received, accepted, in-progress, on-hold}`, ordered by authored date descending.
2. For each Task, shows: patient name, referring GP name, ServiceRequest code/specialty,
   priority, current status, and time since submission.
3. Lets the Filler click into a Task to see the full referral detail:
   - `GET /filler/task/<task-id>` — fetches the Task + linked ServiceRequest +
     DocumentReferences (clinical context, patient summary hint) and renders them.
4. Provides **status action buttons** that issue a `PUT /filler/task/<task-id>/status` (proxied
   to `PUT [SRV]/Task/<task-id>`):
   - **Accept** → `Task.status = accepted`
   - **Begin** → `Task.status = in-progress`
   - **Complete** → `Task.status = completed`
   - **Reject** → `Task.status = rejected` (requires a `statusReason` text input)
   - **Cancel** → `Task.status = cancelled` (requires a `statusReason` text input)
5. All status updates use HTMX `hx-put` so the status badge updates in-place without a full
   page reload. The Placer's patient referral list (proposal 05, future) will reflect the new
   status on next load.

### Task Status Lifecycle Displayed

```
requested → received → accepted → in-progress → completed
                    ↘ rejected
                    ↘ cancelled
         in-progress → on-hold → in-progress
```

Status badges use Bootstrap colour classes:
- `requested` → secondary, `received` → info, `accepted` → primary,
- `in-progress` → warning, `on-hold` → light, `completed` → success,
- `rejected` / `cancelled` / `failed` → danger

## User-Facing Outcome

A user acting as the specialist opens `/filler`, sees a list of incoming referrals, clicks one
to read the clinical context and (if present) the patient summary endpoint hint, then clicks
**Accept** → **Begin** → **Complete** to walk through the status lifecycle. The status badge
updates immediately. Switching back to the patient detail page (Placer view) shows the updated
status, demonstrating end-to-end visibility.

## Non-goals

- Authentication / role separation between Placer and Filler — the demo uses a single mock
  user; role is indicated by which URL the user navigates to.
- Real-time push notifications to the Placer when status changes (no WebSockets; Placer
  refreshes manually or polls).
- Filler creating a new FHIR DiagnosticReport or result resource — fulfilment tracking only.
- Appointment scheduling or slot booking.
- Multi-tenancy or filtering Tasks by organisation — all Tasks on the server are shown.
- Rendering the inline AU PS Bundle (proposal 03 Option A) — only the endpoint hint URL is
  displayed as a clickable link.

## FHIR Operations

| Operation | Endpoint | Purpose |
|---|---|---|
| `GET Task` | `[SRV]/Task?status=requested,received,accepted,in-progress,on-hold&_include=Task:focus` | List open Tasks + linked ServiceRequests |
| `GET Task/<id>` | `[SRV]/Task/<id>?_include=Task:focus&_include=Task:patient` | Full task detail |
| `GET DocumentReference` | `[SRV]/DocumentReference?related=[ServiceRequest/<id>]` | Fetch clinical context + PS hint |
| `PUT Task/<id>` | `[SRV]/Task/<id>` | Update Task status (full resource replace) |

## Impact

- **New routes in `app.py`:**
  - `GET /filler` — Filler dashboard (Task list)
  - `GET /filler/task/<task-id>` — Task detail + referral info
  - `PUT /filler/task/<task-id>/status` — proxy status update to FHIR server (HTMX target)
- **New templates:**
  - `templates/filler_dashboard.html` — Task list with status badges and HTMX actions
  - `templates/filler_task_detail.html` — Full referral view with action buttons
- **New sidebar link:** "Filler View" nav item in the shared sidebar (or a role-switcher banner)
- **No new env vars** (same FHIR server as Placer)
- **No changes** to `bundler.py`, `referral_bundler.py`, or existing diagnostic request flow

## Open Questions

1. Should the Filler dashboard show **all** Tasks on the server, or only Tasks where
   `Task.owner` matches a configured organisation? For the demo, all Tasks is simpler.
2. Is a full resource `PUT` the right verb for status updates, or should we use a FHIR `PATCH`
   (JSON Patch) to update only `Task.status` and `Task.statusReason`? `PUT` is simpler to
   implement; `PATCH` is more correct but requires the server to support it.
3. Should `statusReason` for Reject/Cancel be free text or drawn from a value set? Free text is
   sufficient for the demo.
4. Does the Sparked event server enforce `Task.owner` or `Task.requester` constraints that would
   prevent a Filler from updating Tasks created by a different system?
