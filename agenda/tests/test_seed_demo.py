import pytest
from django.core.management import CommandError, call_command

from agenda.models import (
    DayConfig,
    Requester,
    ScheduleException,
    Service,
    Worker,
    WorkSchedule,
)


@pytest.mark.django_db
class TestSeedDemoCommand:
    def test_seed_demo_creates_data_and_is_idempotent(self, settings):
        settings.DEBUG = True

        # First execution
        call_command("seed_demo")

        assert Service.objects.count() == 3
        assert Worker.objects.count() == 3
        assert WorkSchedule.objects.count() == 15  # 3 workers * 5 days
        assert DayConfig.objects.count() == 7  # 5 open weekdays + 2 closed weekend days
        assert ScheduleException.objects.count() == 1
        assert Requester.objects.count() == 1

        # Second execution (Idempotent: counts and contents should remain the same)
        call_command("seed_demo")

        assert Service.objects.count() == 3
        assert Worker.objects.count() == 3
        assert WorkSchedule.objects.count() == 15
        assert DayConfig.objects.count() == 7
        assert ScheduleException.objects.count() == 1
        assert Requester.objects.count() == 1

    def test_seed_demo_fails_when_debug_is_false(self, settings):
        settings.DEBUG = False
        with pytest.raises(CommandError, match="DEBUG=True"):
            call_command("seed_demo")
