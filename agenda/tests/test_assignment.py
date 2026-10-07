"""Unit tests for worker assignment algorithm (pick_worker) in isolation."""

import datetime
from types import SimpleNamespace

from agenda.services.assignment import pick_worker
from agenda.services.capacity import Interval


def create_mock_worker(worker_id: int, full_name: str = "") -> SimpleNamespace:
    return SimpleNamespace(id=worker_id, full_name=full_name or f"Worker {worker_id}")


def test_pick_worker_single_free_worker():
    w1 = create_mock_worker(1)
    slot = Interval(datetime.time(9, 0), datetime.time(9, 30))

    chosen = pick_worker(
        candidates=[w1],
        slot_interval=slot,
        busy_map={},
        daily_loads={},
    )
    assert chosen == w1


def test_pick_worker_lowest_load_preference():
    w1 = create_mock_worker(1)
    w2 = create_mock_worker(2)
    slot = Interval(datetime.time(10, 0), datetime.time(10, 30))

    # w1 has 2 appointments on the day, w2 has 1
    busy_map = {
        1: [
            Interval(datetime.time(8, 0), datetime.time(8, 30)),
            Interval(datetime.time(9, 0), datetime.time(9, 30)),
        ],
        2: [
            Interval(datetime.time(8, 0), datetime.time(8, 30)),
        ],
    }
    daily_loads = {1: 2, 2: 1}

    chosen = pick_worker(
        candidates=[w1, w2],
        slot_interval=slot,
        busy_map=busy_map,
        daily_loads=daily_loads,
    )
    assert chosen == w2


def test_pick_worker_tie_break_by_lowest_id():
    w1 = create_mock_worker(10)
    w2 = create_mock_worker(20)
    slot = Interval(datetime.time(11, 0), datetime.time(11, 30))

    # Both have load 1
    daily_loads = {10: 1, 20: 1}

    # Pass in reverse order to ensure sorting by id is deterministic
    chosen = pick_worker(
        candidates=[w2, w1],
        slot_interval=slot,
        busy_map={},
        daily_loads=daily_loads,
    )
    assert chosen == w1


def test_pick_worker_skips_overlapping_worker():
    w1 = create_mock_worker(1)
    w2 = create_mock_worker(2)
    slot = Interval(datetime.time(9, 0), datetime.time(9, 30))

    # w1 is busy at 9:00 - 9:30, w2 is free but has load 3
    busy_map = {
        1: [Interval(datetime.time(9, 0), datetime.time(9, 30))],
        2: [],
    }
    daily_loads = {1: 1, 2: 3}

    chosen = pick_worker(
        candidates=[w1, w2],
        slot_interval=slot,
        busy_map=busy_map,
        daily_loads=daily_loads,
    )
    assert chosen == w2


def test_pick_worker_all_busy_returns_none():
    w1 = create_mock_worker(1)
    slot = Interval(datetime.time(9, 0), datetime.time(9, 30))

    busy_map = {
        1: [Interval(datetime.time(9, 15), datetime.time(9, 45))],
    }

    chosen = pick_worker(
        candidates=[w1],
        slot_interval=slot,
        busy_map=busy_map,
        daily_loads={1: 1},
    )
    assert chosen is None


def test_pick_worker_empty_candidates_returns_none():
    slot = Interval(datetime.time(9, 0), datetime.time(9, 30))
    chosen = pick_worker(
        candidates=[],
        slot_interval=slot,
        busy_map={},
        daily_loads={},
    )
    assert chosen is None
