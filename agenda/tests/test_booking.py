"""Unit tests for booking service (book_appointment)."""

import datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings

from agenda.constants import AppointmentStatus
from agenda.exceptions import (
    DayClosed,
    InvalidSlot,
    OutsideBookingWindow,
    QuotaExceeded,
    RequesterLimitReached,
    ScheduleConflict,
    ServiceNotFound,
    WaitlistFull,
)
from agenda.models import AppointmentEvent, DayConfig, Weekday
from agenda.services.booking import book_appointment
from agenda.tests.factories import (
    DayConfigFactory,
    RequesterFactory,
    ServiceFactory,
    WorkerFactory,
    WorkScheduleFactory,
)


@pytest.fixture
def setup_booking_env():
    tz = ZoneInfo(settings.TIME_ZONE)
    # Fixed date: Monday 2026-10-12
    booking_date = datetime.date(2026, 10, 12)
    now_fixed = datetime.datetime(2026, 10, 10, 10, 0, tzinfo=tz)

    service = ServiceFactory(duration_minutes=30, is_active=True)
    w1 = WorkerFactory(id=1, full_name="Worker One")
    w2 = WorkerFactory(id=2, full_name="Worker Two")

    # Both workers work Monday 09:00 - 17:00, break 13:00 - 14:00
    for w in (w1, w2):
        WorkScheduleFactory(
            worker=w,
            weekday=Weekday.MONDAY,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
            break_start=datetime.time(13, 0),
            break_end=datetime.time(14, 0),
        )

    # DayConfig: open, max 10 appointments
    DayConfigFactory(
        weekday=Weekday.MONDAY,
        is_open=True,
        max_appointments=10,
    )

    requester = RequesterFactory()

    return {
        "tz": tz,
        "date": booking_date,
        "now": now_fixed,
        "service": service,
        "workers": (w1, w2),
        "requester": requester,
    }


@pytest.mark.django_db
def test_book_appointment_confirmed_happy_path(setup_booking_env):
    env = setup_booking_env
    start_at = datetime.datetime(2026, 10, 12, 9, 0, tzinfo=env["tz"])

    result = book_appointment(
        requester=env["requester"],
        service=env["service"],
        start_at=start_at,
        now=env["now"],
    )

    assert result.outcome == AppointmentStatus.CONFIRMED
    assert result.appointment.status == AppointmentStatus.CONFIRMED
    assert result.appointment.worker == env["workers"][0]  # tie-break worker 1
    assert result.appointment.date == env["date"]

    events = AppointmentEvent.objects.filter(appointment=result.appointment)
    assert events.count() == 1
    event = events.first()
    assert event.to_status == AppointmentStatus.CONFIRMED
    assert event.worker == env["workers"][0]


@pytest.mark.django_db
def test_book_appointment_load_balancing_and_tie_breaking(setup_booking_env):
    env = setup_booking_env
    w1, w2 = env["workers"]

    # 1. First booking: 09:00 -> w1 assigned (both load 0, tie-break id 1)
    req1 = RequesterFactory()
    res1 = book_appointment(
        requester=req1,
        service=env["service"],
        start_at=datetime.datetime(2026, 10, 12, 9, 0, tzinfo=env["tz"]),
        now=env["now"],
    )
    assert res1.appointment.worker == w1

    # 2. Second booking: 10:00 -> w2 assigned (w1 load 1, w2 load 0)
    req2 = RequesterFactory()
    res2 = book_appointment(
        requester=req2,
        service=env["service"],
        start_at=datetime.datetime(2026, 10, 12, 10, 0, tzinfo=env["tz"]),
        now=env["now"],
    )
    assert res2.appointment.worker == w2


@pytest.mark.django_db
def test_book_appointment_waitlist_when_no_worker_free(setup_booking_env):
    env = setup_booking_env
    w1, w2 = env["workers"]
    slot_start = datetime.datetime(2026, 10, 12, 9, 0, tzinfo=env["tz"])

    # Fill slot for w1
    req1 = RequesterFactory()
    res1 = book_appointment(
        requester=req1,
        service=env["service"],
        start_at=slot_start,
        now=env["now"],
    )
    assert res1.appointment.worker == w1

    # Fill slot for w2
    req2 = RequesterFactory()
    res2 = book_appointment(
        requester=req2,
        service=env["service"],
        start_at=slot_start,
        now=env["now"],
    )
    assert res2.appointment.worker == w2

    # Third booking for the same slot -> Waitlisted!
    req3 = RequesterFactory()
    res3 = book_appointment(
        requester=req3,
        service=env["service"],
        start_at=slot_start,
        now=env["now"],
    )
    assert res3.outcome == AppointmentStatus.WAITLISTED
    assert res3.appointment.status == AppointmentStatus.WAITLISTED
    assert res3.appointment.worker is None

    event = AppointmentEvent.objects.filter(appointment=res3.appointment).first()
    assert event.to_status == AppointmentStatus.WAITLISTED


@pytest.mark.django_db
def test_book_appointment_waitlist_full(setup_booking_env, settings):
    env = setup_booking_env
    settings.WAITLIST_MAX_PER_DAY = 1

    slot_start = datetime.datetime(2026, 10, 12, 9, 0, tzinfo=env["tz"])

    # Fill both workers
    book_appointment(
        requester=RequesterFactory(),
        service=env["service"],
        start_at=slot_start,
        now=env["now"],
    )
    book_appointment(
        requester=RequesterFactory(),
        service=env["service"],
        start_at=slot_start,
        now=env["now"],
    )

    # 1st waitlisted appointment (reaches limit 1)
    book_appointment(
        requester=RequesterFactory(),
        service=env["service"],
        start_at=slot_start,
        now=env["now"],
    )

    # 2nd waitlisted appointment -> WaitlistFull
    with pytest.raises(WaitlistFull):
        book_appointment(
            requester=RequesterFactory(),
            service=env["service"],
            start_at=slot_start,
            now=env["now"],
        )


@pytest.mark.django_db
def test_book_appointment_inactive_service_raises_service_not_found(setup_booking_env):
    env = setup_booking_env
    env["service"].is_active = False
    env["service"].save()

    with pytest.raises(ServiceNotFound):
        book_appointment(
            requester=env["requester"],
            service=env["service"],
            start_at=datetime.datetime(2026, 10, 12, 9, 0, tzinfo=env["tz"]),
            now=env["now"],
        )


@pytest.mark.django_db
def test_book_appointment_naive_start_at_raises_invalid_slot(setup_booking_env):
    env = setup_booking_env
    naive_dt = datetime.datetime(2026, 10, 12, 9, 0)

    with pytest.raises(InvalidSlot):
        book_appointment(
            requester=env["requester"],
            service=env["service"],
            start_at=naive_dt,
            now=env["now"],
        )


@pytest.mark.django_db
def test_book_appointment_outside_booking_window(setup_booking_env):
    env = setup_booking_env

    # 1. In the past
    past_dt = datetime.datetime(2026, 10, 9, 9, 0, tzinfo=env["tz"])
    with pytest.raises(OutsideBookingWindow):
        book_appointment(
            requester=env["requester"],
            service=env["service"],
            start_at=past_dt,
            now=env["now"],
        )

    # 2. Too soon (< BOOKING_MIN_ADVANCE_HOURS = 2 hours)
    too_soon_dt = env["now"] + datetime.timedelta(hours=1)
    with pytest.raises(OutsideBookingWindow):
        book_appointment(
            requester=env["requester"],
            service=env["service"],
            start_at=too_soon_dt,
            now=env["now"],
        )

    # 3. Beyond BOOKING_MAX_ADVANCE_DAYS (60 days)
    far_future_dt = env["now"] + datetime.timedelta(days=70)
    with pytest.raises(OutsideBookingWindow):
        book_appointment(
            requester=env["requester"],
            service=env["service"],
            start_at=far_future_dt,
            now=env["now"],
        )


@pytest.mark.django_db
def test_book_appointment_day_closed(setup_booking_env):
    env = setup_booking_env

    # Close the day explicitly
    DayConfig.objects.filter(weekday=Weekday.MONDAY).update(is_open=False)

    with pytest.raises(DayClosed):
        book_appointment(
            requester=env["requester"],
            service=env["service"],
            start_at=datetime.datetime(2026, 10, 12, 9, 0, tzinfo=env["tz"]),
            now=env["now"],
        )


@pytest.mark.django_db
def test_book_appointment_invalid_slot_alignment_or_breaks(setup_booking_env):
    env = setup_booking_env

    # 1. Misaligned minutes (not multiple of 15)
    misaligned_dt = datetime.datetime(2026, 10, 12, 9, 7, tzinfo=env["tz"])
    with pytest.raises(InvalidSlot):
        book_appointment(
            requester=env["requester"],
            service=env["service"],
            start_at=misaligned_dt,
            now=env["now"],
        )

    # 2. Slot crosses break (break is 13:00 - 14:00, slot 12:45 - 13:15)
    cross_break_dt = datetime.datetime(2026, 10, 12, 12, 45, tzinfo=env["tz"])
    with pytest.raises(InvalidSlot):
        book_appointment(
            requester=env["requester"],
            service=env["service"],
            start_at=cross_break_dt,
            now=env["now"],
        )

    # 3. Outside shift hours (after 17:00)
    outside_hours_dt = datetime.datetime(2026, 10, 12, 18, 0, tzinfo=env["tz"])
    with pytest.raises(InvalidSlot):
        book_appointment(
            requester=env["requester"],
            service=env["service"],
            start_at=outside_hours_dt,
            now=env["now"],
        )


@pytest.mark.django_db
def test_book_appointment_quota_exceeded(setup_booking_env):
    env = setup_booking_env

    # Limit quota to 2 appointments
    DayConfig.objects.filter(weekday=Weekday.MONDAY).update(max_appointments=2)

    # 1st appointment
    book_appointment(
        requester=RequesterFactory(),
        service=env["service"],
        start_at=datetime.datetime(2026, 10, 12, 9, 0, tzinfo=env["tz"]),
        now=env["now"],
    )
    # 2nd appointment
    book_appointment(
        requester=RequesterFactory(),
        service=env["service"],
        start_at=datetime.datetime(2026, 10, 12, 9, 30, tzinfo=env["tz"]),
        now=env["now"],
    )

    # 3rd appointment -> QuotaExceeded
    with pytest.raises(QuotaExceeded):
        book_appointment(
            requester=RequesterFactory(),
            service=env["service"],
            start_at=datetime.datetime(2026, 10, 12, 10, 0, tzinfo=env["tz"]),
            now=env["now"],
        )


@pytest.mark.django_db
def test_book_appointment_requester_limits_and_conflicts(setup_booking_env, settings):
    env = setup_booking_env

    # 1. With MAX_ACTIVE_PER_REQUESTER_PER_DAY = 1 (default)
    book_appointment(
        requester=env["requester"],
        service=env["service"],
        start_at=datetime.datetime(2026, 10, 12, 9, 0, tzinfo=env["tz"]),
        now=env["now"],
    )

    # Second active appointment on the same date for the same requester -> RequesterLimitReached
    with pytest.raises(RequesterLimitReached):
        book_appointment(
            requester=env["requester"],
            service=env["service"],
            start_at=datetime.datetime(2026, 10, 12, 10, 0, tzinfo=env["tz"]),
            now=env["now"],
        )

    # 2. With MAX_ACTIVE_PER_REQUESTER_PER_DAY = 2, overlapping slot -> ScheduleConflict
    settings.MAX_ACTIVE_PER_REQUESTER_PER_DAY = 2
    with pytest.raises(ScheduleConflict):
        book_appointment(
            requester=env["requester"],
            service=env["service"],
            start_at=datetime.datetime(2026, 10, 12, 9, 15, tzinfo=env["tz"]),
            now=env["now"],
        )


@pytest.mark.django_db
def test_book_appointment_respects_day_config_custom_settings(setup_booking_env):
    env = setup_booking_env
    # Booking date is Monday 2026-10-12
    booking_date = env["date"]
    monday_morning = datetime.datetime.combine(booking_date, datetime.time(7, 0), tzinfo=env["tz"])

    # Override min advance hours to 5 for this weekday (default is 2)
    DayConfig.objects.filter(weekday=Weekday.MONDAY).update(booking_min_advance_hours=5)

    # Monday 10:00 is 3 hours ahead (allowed under default 2h, but rejected under 5h)
    slot_10am = datetime.datetime.combine(booking_date, datetime.time(10, 0), tzinfo=env["tz"])
    with pytest.raises(OutsideBookingWindow):
        book_appointment(
            requester=env["requester"],
            service=env["service"],
            start_at=slot_10am,
            now=monday_morning,
        )

    # Monday 14:00 is 7 hours ahead (exceeds 5h min advance, so it succeeds)
    slot_2pm = datetime.datetime.combine(booking_date, datetime.time(14, 0), tzinfo=env["tz"])
    res = book_appointment(
        requester=env["requester"],
        service=env["service"],
        start_at=slot_2pm,
        now=monday_morning,
    )
    assert res.appointment.status == AppointmentStatus.CONFIRMED
