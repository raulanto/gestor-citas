"""Tests for pure capacity calculations and slot generation in agenda/services/capacity.py."""

import datetime

import pytest

from agenda.selectors.types import Shift
from agenda.services.capacity import (
    Interval,
    effective_quota,
    generate_slots,
    personnel_capacity,
    work_segments,
    worker_capacity,
)


class TestInterval:
    def test_invalid_interval_raises_error(self):
        with pytest.raises(ValueError, match="must be before end"):
            Interval(start=datetime.time(10, 0), end=datetime.time(9, 0))

        with pytest.raises(ValueError, match="must be before end"):
            Interval(start=datetime.time(10, 0), end=datetime.time(10, 0))

    def test_duration_minutes(self):
        interval = Interval(start=datetime.time(9, 15), end=datetime.time(11, 45))
        assert interval.duration_minutes == 150

    def test_overlaps_semi_open_behavior(self):
        i1 = Interval(start=datetime.time(9, 0), end=datetime.time(10, 0))
        i2 = Interval(start=datetime.time(10, 0), end=datetime.time(11, 0))
        # Touching at the boundary does NOT overlap
        assert i1.overlaps(i2) is False
        assert i2.overlaps(i1) is False

        # Partially overlapping
        i3 = Interval(start=datetime.time(9, 30), end=datetime.time(10, 30))
        assert i1.overlaps(i3) is True
        assert i3.overlaps(i1) is True

        # Completely contained
        i_container = Interval(start=datetime.time(8, 0), end=datetime.time(12, 0))
        assert i_container.overlaps(i1) is True
        assert i1.overlaps(i_container) is True

        # Completely disjoint
        i_disjoint = Interval(start=datetime.time(14, 0), end=datetime.time(16, 0))
        assert i1.overlaps(i_disjoint) is False
        assert i_disjoint.overlaps(i1) is False


class TestWorkSegments:
    def test_shift_without_break(self):
        shift = Shift(start=datetime.time(9, 0), end=datetime.time(17, 0))
        segments = work_segments(shift)
        assert len(segments) == 1
        assert segments[0] == Interval(start=datetime.time(9, 0), end=datetime.time(17, 0))

    def test_shift_with_break(self):
        shift = Shift(
            start=datetime.time(9, 0),
            end=datetime.time(17, 0),
            break_start=datetime.time(13, 0),
            break_end=datetime.time(14, 0),
        )
        segments = work_segments(shift)
        assert len(segments) == 2
        assert segments[0] == Interval(start=datetime.time(9, 0), end=datetime.time(13, 0))
        assert segments[1] == Interval(start=datetime.time(14, 0), end=datetime.time(17, 0))


class TestWorkerCapacity:
    def test_shift_without_break_capacity(self):
        # 09:00 - 17:00 (8 hours = 480 mins), duration 30 min -> 16 appointments
        shift = Shift(start=datetime.time(9, 0), end=datetime.time(17, 0))
        assert worker_capacity(shift, 30) == 16

    def test_shift_with_break_capacity(self):
        # 09:00 - 17:00 with break 13:00 - 14:00 (4h segment + 3h segment), duration 60 min
        # (4 // 1) + (3 // 1) = 4 + 3 = 7
        shift = Shift(
            start=datetime.time(9, 0),
            end=datetime.time(17, 0),
            break_start=datetime.time(13, 0),
            break_end=datetime.time(14, 0),
        )
        assert worker_capacity(shift, 60) == 7

    def test_shift_where_break_splits_unusable_blocks(self):
        # 09:00 - 10:50, break 09:50 - 10:00, duration 60 min
        # Segment 1: 09:00 - 09:50 (50 min -> 0 appointments)
        # Segment 2: 10:00 - 10:50 (50 min -> 0 appointments)
        # Old formula gave floor((110 - 10) / 60) = 1, new continuous segment formula gives 0
        shift = Shift(
            start=datetime.time(9, 0),
            end=datetime.time(10, 50),
            break_start=datetime.time(9, 50),
            break_end=datetime.time(10, 0),
        )
        assert worker_capacity(shift, 60) == 0

    def test_zero_or_negative_duration_gives_zero(self):
        shift = Shift(start=datetime.time(9, 0), end=datetime.time(17, 0))
        assert worker_capacity(shift, 0) == 0
        assert worker_capacity(shift, -15) == 0


class TestGenerateSlots:
    def test_slots_do_not_cross_break_or_shift_end(self):
        # Shift 09:00 - 11:00 with break 09:45 - 10:15
        # Segment 1: 09:00 - 09:45
        #   Slots with duration 30, step 15:
        #   - 09:00 - 09:30
        #   - 09:15 - 09:45
        # Segment 2: 10:15 - 11:00
        #   - 10:15 - 10:45
        #   - 10:30 - 11:00
        shift = Shift(
            start=datetime.time(9, 0),
            end=datetime.time(11, 0),
            break_start=datetime.time(9, 45),
            break_end=datetime.time(10, 15),
        )
        slots = generate_slots(shift, duration_minutes=30, step_minutes=15)
        expected = [
            Interval(datetime.time(9, 0), datetime.time(9, 30)),
            Interval(datetime.time(9, 15), datetime.time(9, 45)),
            Interval(datetime.time(10, 15), datetime.time(10, 45)),
            Interval(datetime.time(10, 30), datetime.time(11, 0)),
        ]
        assert slots == expected


class TestPersonnelCapacityAndEffectiveQuota:
    def test_personnel_capacity_sums_all_workers(self):
        shift1 = Shift(start=datetime.time(9, 0), end=datetime.time(17, 0))  # 16 slots (30 min)
        shift2 = Shift(start=datetime.time(8, 0), end=datetime.time(12, 0))  # 8 slots (30 min)
        assert personnel_capacity([shift1, shift2], 30) == 24

    def test_effective_quota_calculations(self):
        # max_appointments is None -> personnel capacity
        assert effective_quota(None, 24) == 24

        # max_appointments lower than capacity -> max_appointments
        assert effective_quota(10, 24) == 10

        # capacity lower than max_appointments -> capacity
        assert effective_quota(30, 24) == 24

        # max_appointments is 0 -> 0
        assert effective_quota(0, 24) == 0
