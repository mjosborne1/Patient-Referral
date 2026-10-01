"""Flask routes for imaging appointment booking (see booking.py)."""
import os
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from flask import Blueprint, make_response, render_template, request
from flask_login import login_required

from booking import DEFAULT_TIMEZONE, IMAGING_SERVICE_TYPES, BookingClient, FhirError
from fhirutils import get_fhir_auth_credentials, get_fhir_bearer_token, get_fhir_server_url

booking_bp = Blueprint("booking", __name__)


def _env_flag(name, default=True):
    return os.environ.get(name, str(default)).lower() not in ("false", "0", "no")


def _client():
    return BookingClient(get_fhir_server_url(), auth=get_fhir_auth_credentials(),
                         bearer=get_fhir_bearer_token(),
                         verify=_env_flag("FHIR_VERIFY_SSL"))


@booking_bp.route("/filler/imaging")
@login_required
def filler_imaging():
    return render_template("filler_imaging.html", service_types=IMAGING_SERVICE_TYPES.values(),
                           today=date.today().isoformat())


@booking_bp.route("/filler/imaging/availability", methods=["POST"])
@login_required
def publish_availability():
    form = request.form
    result = _client().publish_availability(
        organization_id=form["organization_id"].strip(),
        location_id=form["location_id"].strip(),
        service_type=IMAGING_SERVICE_TYPES[form["service_type"]],
        start_date=date.fromisoformat(form["start_date"]),
        end_date=date.fromisoformat(form["end_date"]),
        day_start=time.fromisoformat(form["day_start"]),
        day_end=time.fromisoformat(form["day_end"]),
        slot_minutes=int(form["slot_minutes"]),
        claim_profiles=_env_flag("CLAIM_BOOKING_PROFILES"),
    )
    return render_template("partials/booking_publish_result.html", result=result)


@booking_bp.route("/filler/imaging/locations")
@login_required
def filler_imaging_locations():
    locations = _client().locations_for_organization(request.args["organization_id"])
    return render_template("partials/booking_location_options.html", locations=locations)


# ── Placer: Requests & Appointments panel ────────────────────────────────────

@booking_bp.app_template_filter("booking_day")
def booking_day(value):
    """'Tue 6 Oct' for a FHIR instant, in the booking timezone."""
    moment = _local(value)
    return f"{moment:%a} {moment.day} {moment:%b}"


@booking_bp.app_template_filter("booking_time")
def booking_time(value):
    return f"{_local(value):%H:%M}"


def _local(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        ZoneInfo(os.environ.get("BOOKING_TIMEZONE", DEFAULT_TIMEZONE)))


@booking_bp.route("/booking/patient/<patient_id>/panel")
@login_required
def placer_panel(patient_id):
    try:
        rows = _client().patient_imaging_requests(patient_id)
    except FhirError as error:
        return render_template("partials/operation_outcome.html", outcome=error.operation_outcome)
    return render_template("partials/booking_panel.html", rows=rows, patient_id=patient_id)


def _render_slot_picker(service_request_id, notice=None, *, action_url=None,
                        ask_instruction=False):
    result = _client().free_slots(service_request_id)
    if not result.ok:
        return render_template("partials/operation_outcome.html", outcome=result.operation_outcome)
    days = {}
    for slot, schedule in result.slots:
        days.setdefault(booking_day(slot["start"]), []).append((slot, schedule))
    return render_template("partials/booking_slot_picker.html", days=days, notice=notice,
                           service_request=result.service_request,
                           action_url=action_url or f"/booking/sr/{service_request_id}/propose",
                           ask_instruction=ask_instruction)


@booking_bp.route("/booking/sr/<service_request_id>/slots")
@login_required
def slot_picker(service_request_id):
    return _render_slot_picker(service_request_id)


@booking_bp.route("/booking/sr/<service_request_id>/propose", methods=["POST"])
@login_required
def propose(service_request_id):
    result = _client().propose(service_request_id, request.form["slot_id"],
                               claim_profiles=_env_flag("CLAIM_BOOKING_PROFILES"))
    if result.conflict:
        return _render_slot_picker(service_request_id,
                                   notice="This slot was just taken — please choose another.")
    if not result.ok:
        return render_template("partials/operation_outcome.html", outcome=result.operation_outcome)
    response = make_response(render_template("partials/booking_proposed.html"))
    response.headers["HX-Trigger"] = "booking-changed"
    return response


# ── Filler: pending bookings ─────────────────────────────────────────────────

def _booking_changed(template, **context):
    response = make_response(render_template(template, **context))
    response.headers["HX-Trigger"] = "booking-changed"
    return response


def _booking_outcome(result, done_label):
    if result.conflict:
        return _booking_changed("partials/booking_action_result.html", ok=False,
                                message="This booking has changed since it was listed — "
                                        "the list has been refreshed.")
    if not result.ok:
        return render_template("partials/operation_outcome.html", outcome=result.operation_outcome)
    return _booking_changed("partials/booking_action_result.html", ok=True, message=done_label)


@booking_bp.route("/filler/imaging/pending")
@login_required
def filler_pending():
    try:
        pending = _client().pending_appointments(request.args["organization_id"])
    except FhirError as error:
        return render_template("partials/operation_outcome.html", outcome=error.operation_outcome)
    return render_template("partials/booking_pending_list.html", pending=pending)


@booking_bp.route("/filler/imaging/appointment/<appointment_id>/confirm", methods=["POST"])
@login_required
def filler_confirm(appointment_id):
    instruction = request.form.get("patient_instruction", "").strip() or None
    return _booking_outcome(_client().confirm(appointment_id, patient_instruction=instruction),
                            "Booked")


@booking_bp.route("/filler/imaging/appointment/<appointment_id>/decline", methods=["POST"])
@login_required
def filler_decline(appointment_id):
    reason = request.form.get("reason", "").strip()
    if not reason:
        return render_template("partials/booking_action_result.html", ok=False,
                               message="A reason is required to decline a booking.")
    return _booking_outcome(_client().decline(appointment_id, reason=reason), "Declined")


# ── Filler: direct booking (IG variant) ─────────────────────────────────────

@booking_bp.route("/filler/imaging/unbooked")
@login_required
def filler_unbooked():
    try:
        rows = _client().unbooked_requests(request.args["organization_id"])
    except FhirError as error:
        return render_template("partials/operation_outcome.html", outcome=error.operation_outcome)
    return render_template("partials/booking_unbooked_list.html", rows=rows)


def _filler_slot_picker(service_request_id, notice=None):
    return _render_slot_picker(service_request_id, notice,
                               action_url=f"/filler/imaging/sr/{service_request_id}/book",
                               ask_instruction=True)


@booking_bp.route("/filler/imaging/sr/<service_request_id>/slots")
@login_required
def filler_slot_picker(service_request_id):
    return _filler_slot_picker(service_request_id)


@booking_bp.route("/filler/imaging/sr/<service_request_id>/book", methods=["POST"])
@login_required
def filler_book(service_request_id):
    result = _client().book_directly(
        service_request_id, request.form["slot_id"],
        patient_instruction=request.form.get("patient_instruction", "").strip() or None,
        claim_profiles=_env_flag("CLAIM_BOOKING_PROFILES"))
    if result.conflict:
        return _filler_slot_picker(service_request_id,
                                   notice="This slot was just taken — please choose another.")
    return _booking_outcome(result, "Booked")
