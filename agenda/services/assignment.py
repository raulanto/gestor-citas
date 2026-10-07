"""Worker assignment service for appointments."""

from collections.abc import Sequence

from agenda.models import Worker
from agenda.services.capacity import Interval


def pick_worker(
    *,
    candidates: Sequence[Worker],
    slot_interval: Interval,
    busy_map: dict[int, Sequence[Interval]],
    daily_loads: dict[int, int],
) -> Worker | None:
    """Select the best candidate worker for an appointment slot.

    Picks the worker who is free during `slot_interval` and has the lowest daily load
    (number of occupying appointments on that date).
    Ties are broken by lowest worker id.

    Returns None if no candidate worker is available.
    """
    free_candidates: list[tuple[int, int, Worker]] = []

    for worker in candidates:
        worker_busy = busy_map.get(worker.id, [])
        is_free = not any(slot_interval.overlaps(busy) for busy in worker_busy)
        if is_free:
            load = daily_loads.get(worker.id, 0)
            free_candidates.append((load, worker.id, worker))

    if not free_candidates:
        return None

    free_candidates.sort(key=lambda item: (item[0], item[1]))
    return free_candidates[0][2]
