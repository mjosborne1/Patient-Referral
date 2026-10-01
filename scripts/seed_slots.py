"""Publish free imaging Slots for a filler organisation from the command line.

Example:
    python scripts/seed_slots.py --org organization-northside-imaging \\
        --location location-northside-imaging-chermside --service 310128004 --days 14
"""
import argparse
import os
import sys
from datetime import date, time, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from booking import IMAGING_SERVICE_TYPES, BookingClient  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--server", default=os.environ.get("FHIR_SERVER_URL",
                                                           "https://aucore.aidbox.beda.software/fhir"))
    parser.add_argument("--org", required=True, help="Filler Organization id")
    parser.add_argument("--location", required=True, help="Location id")
    parser.add_argument("--service", default="310128004", choices=sorted(IMAGING_SERVICE_TYPES),
                        help="SNOMED imaging service code (default: CT)")
    parser.add_argument("--start", type=date.fromisoformat, default=date.today())
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--day-start", type=time.fromisoformat, default=time(9, 0))
    parser.add_argument("--day-end", type=time.fromisoformat, default=time(17, 0))
    parser.add_argument("--slot-minutes", type=int, default=30)
    parser.add_argument("--no-profiles", action="store_true", help="Do not claim IG profiles")
    args = parser.parse_args(argv)

    user, password = os.environ.get("FHIR_USERNAME"), os.environ.get("FHIR_PASSWORD")
    client = BookingClient(args.server, auth=(user, password) if user and password else None)
    result = client.publish_availability(
        organization_id=args.org, location_id=args.location,
        service_type=IMAGING_SERVICE_TYPES[args.service],
        start_date=args.start, end_date=args.start + timedelta(days=args.days - 1),
        day_start=args.day_start, day_end=args.day_end, slot_minutes=args.slot_minutes,
        claim_profiles=not args.no_profiles)
    if not result.ok:
        for issue in result.operation_outcome.get("issue", []):
            print(f"{issue.get('severity')}: {issue.get('diagnostics')}", file=sys.stderr)
        return 1
    print(f"Published {result.created_slots} slots ({result.skipped_slots} already published)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
