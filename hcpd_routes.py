"""Flask routes for importing providers from the HCPD bulk export (see hcpd_export.py)."""
import os
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, current_app, make_response, render_template, request
from flask_login import login_required

from fhirutils import get_fhir_auth_credentials, get_fhir_bearer_token, get_fhir_server_url
from hcpd_export import (ExportRequestError, HcpdExportClient, JobAlreadyActive, JobRunner,
                         JobStore, ReferralImporter, StaticToken, build_export_parameters,
                         jwt_expiry, scope_filters, token_from_env)
from provider_directory import pd_server

hcpd_bp = Blueprint("hcpd", __name__)

IMPORT_TYPES = ["Organization", "Location", "HealthcareService", "PractitionerRole",
                "Practitioner", "Endpoint"]
PRESETS = [("geographic", "Geographic (state)", "QLD"),
           ("service-type", "Service type", "http://snomed.info/sct|310128004"),
           ("organisation", "Organisation (HPI-O system|value, or name)",
            "http://ns.electronichealth.net.au/id/hi/hpio/1.0|8003623233370062"),
           ("advanced", "Advanced (raw _typeFilter lines)", "")]


def hcpd_base():
    return os.environ.get("HCPD_EXPORT_SERVER", "").rstrip("/") or pd_server()


def _tokens():
    tokens = current_app.extensions.get("hcpd_tokens")
    if tokens is None:
        tokens = token_from_env()
        current_app.extensions["hcpd_tokens"] = tokens
    return tokens


def _auth_status():
    """(mode, expires) for the page: oauth | static | none, and a static JWT's expiry if known."""
    tokens = token_from_env()  # re-read so .env edits show without a restart
    if not isinstance(tokens, StaticToken):
        return "oauth", None
    if not tokens():
        return "none", None
    expiry = jwt_expiry(tokens())
    return "static", datetime.fromtimestamp(expiry, timezone.utc) if expiry else None


def _runner():
    runner = current_app.extensions.get("hcpd_runner")
    if runner is None:
        tokens, base = _tokens(), hcpd_base()
        runner = JobRunner(JobStore(Path(current_app.instance_path) / "hcpd"),
                           hcpd_factory=lambda: HcpdExportClient(base, token=tokens))
        current_app.extensions["hcpd_runner"] = runner
    return runner


def _importer():
    """Referral-server importer bound to this request's server and credentials (kept in memory)."""
    verify = os.environ.get("FHIR_VERIFY_SSL", "true").lower() not in ("false", "0", "no")
    return ReferralImporter(get_fhir_server_url(), auth=get_fhir_auth_credentials(),
                            bearer=get_fhir_bearer_token(), verify=verify,
                            batch_size=int(os.environ.get("HCPD_IMPORT_BATCH_SIZE", "100")))


def _jobs_changed(template, **context):
    response = make_response(render_template(template, **context))
    response.headers["HX-Trigger"] = "hcpd-jobs-changed"
    return response


def _message(text, ok=False):
    return render_template("partials/booking_action_result.html", ok=ok, message=text)


@hcpd_bp.route("/directory/import")
@login_required
def import_page():
    auth_mode, token_expires = _auth_status()
    return render_template("directory_import.html", types=IMPORT_TYPES, presets=PRESETS,
                           hcpd_base=hcpd_base(), auth_mode=auth_mode, token_expires=token_expires,
                           token_expired=bool(token_expires and token_expires < datetime.now(timezone.utc)))


@hcpd_bp.route("/directory/import", methods=["POST"])
@login_required
def start_import():
    form = request.form
    types = form.getlist("types")
    preset = form.get("preset", "")
    try:
        if preset == "advanced":
            filters = [line.strip() for line in form.get("filters", "").splitlines() if line.strip()]
        else:
            filters = scope_filters(preset, form.get("value", ""), types,
                                    state=form.get("state", "").strip() or None)
        parameters = build_export_parameters(types, filters)
        _runner().start(parameters, mode="standard", importer=_importer(), source=hcpd_base())
    except (ExportRequestError, JobAlreadyActive) as error:
        return _message(str(error))
    return _jobs_changed("partials/booking_action_result.html", ok=True,
                         message="Export submitted to HCPD.")


@hcpd_bp.route("/directory/import/jobs")
@login_required
def jobs():
    runner = _runner()
    jobs = runner.store.list()[:20]
    active = runner.store.active()
    return render_template("partials/hcpd_jobs.html", jobs=jobs, active=active,
                           interrupted={j["id"] for j in jobs if runner.is_interrupted(j)},
                           has_sync_point={j["id"] for j in jobs
                                           if runner.store.get_since(j.get("scope_key", ""))})


@hcpd_bp.route("/directory/import/jobs/<job_id>/cancel", methods=["POST"])
@login_required
def cancel(job_id):
    _runner().cancel(job_id)
    return _jobs_changed("partials/booking_action_result.html", ok=True, message="Cancelling…")


@hcpd_bp.route("/directory/import/jobs/<job_id>/resume", methods=["POST"])
@login_required
def resume(job_id):
    _runner().resume(job_id, importer=_importer(), source=hcpd_base())
    return _jobs_changed("partials/booking_action_result.html", ok=True, message="Resumed.")


@hcpd_bp.route("/directory/import/jobs/<job_id>/incremental", methods=["POST"])
@login_required
def incremental(job_id):
    runner = _runner()
    previous = runner.store.get(job_id)
    since = previous and runner.store.get_since(previous["scope_key"])
    if not since:
        return _message("No completed export of this scope to continue from.")
    kept = [p for p in previous["parameters"]["parameter"] if p["name"] in ("_type", "_typeFilter")]
    types = [t for p in kept if p["name"] == "_type" for t in p["valueString"].split(",")]
    filters = [p["valueString"] for p in kept if p["name"] == "_typeFilter"]
    try:
        runner.start(build_export_parameters(types, filters, since=since), mode="incremental",
                     importer=_importer(), source=hcpd_base())
    except (ExportRequestError, JobAlreadyActive) as error:
        return _message(str(error))
    return _jobs_changed("partials/booking_action_result.html", ok=True,
                         message=f"Incremental export since {since} submitted.")
