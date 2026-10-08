from django.conf import settings


def test_timezone_and_i18n_settings():
    """Verify time zone and localization configurations."""
    assert settings.TIME_ZONE == "America/Mexico_City"
    assert settings.USE_TZ is True
    assert settings.LANGUAGE_CODE == "es-mx"


def test_business_limits_constants():
    """Verify that domain limit constants exist in django.conf.settings with correct defaults."""
    assert settings.BOOKING_MIN_ADVANCE_HOURS == 2
    assert settings.BOOKING_MAX_ADVANCE_DAYS == 60
    assert settings.CANCEL_MIN_HOURS == 4
    assert settings.MAX_RESCHEDULES_PER_APPOINTMENT == 2
    assert settings.MAX_ACTIVE_PER_REQUESTER_PER_DAY == 1
    assert settings.WAITLIST_MAX_PER_DAY == 20
    assert settings.DEFAULT_SLOT_STEP_MINUTES == 15


def test_rest_framework_settings():
    """Verify DRF configuration."""
    assert (
        settings.REST_FRAMEWORK["EXCEPTION_HANDLER"]
        == "agenda.api.exception_handler.custom_exception_handler"
    )
    assert settings.REST_FRAMEWORK["PAGE_SIZE"] == 25
    assert settings.PAGINATION_DEFAULT_LIMIT == 25
    assert settings.PAGINATION_MAX_LIMIT == 100
