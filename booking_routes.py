"""Flask routes for imaging appointment booking (see booking.py)."""
import os
from datetime import date, time

from flask import Blueprint, render_template, request
from flask_login import login_required

from booking import IMAGING_SERVICE_TYPES, BookingClient
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
