"""Behaviour of the availability Slot generator."""
from datetime import date, time

from booking import generate_slot_times


def test_one_weekday_yields_back_to_back_slots_within_hours_in_brisbane_time():
    slots = generate_slot_times(
        date(2026, 10, 6), date(2026, 10, 6),
        day_start=time(9, 0), day_end=time(10, 30), slot_minutes=30,
    )

    assert [(s.isoformat(), e.isoformat()) for s, e in slots] == [
        ("2026-10-06T09:00:00+10:00", "2026-10-06T09:30:00+10:00"),
        ("2026-10-06T09:30:00+10:00", "2026-10-06T10:00:00+10:00"),
        ("2026-10-06T10:00:00+10:00", "2026-10-06T10:30:00+10:00"),
    ]


def test_weekends_are_skipped_and_no_partial_slot_runs_past_day_end():
    # Fri 9 Oct .. Mon 12 Oct 2026; 09:00-10:00 with 40-minute slots fits only one.
    slots = generate_slot_times(
        date(2026, 10, 9), date(2026, 10, 12),
        day_start=time(9, 0), day_end=time(10, 0), slot_minutes=40,
    )

    assert [s.isoformat() for s, _ in slots] == [
        "2026-10-09T09:00:00+10:00",
        "2026-10-12T09:00:00+10:00",
    ]
