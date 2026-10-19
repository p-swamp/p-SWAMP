"""``AlarmRaiser``: one alarm per emergency, cleared once it has held off."""

from datetime import datetime, timedelta, timezone

from pswamp_core.alarms import AlarmRaiser
from pswamp_models.common import AppIdentity

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def raiser(**settings) -> AlarmRaiser:
    return AlarmRaiser(AppIdentity(name="test", uuid="0"), **settings)


def test_an_emergency_issues_one_alarm_and_clears_after_the_hold():
    alarms = raiser(hold_s=15)
    assert alarms.update("OK", at(0)) is None
    issued = alarms.update("Emergency", at(1))
    assert (issued.type, issued.status, issued.app.name) == ("init", "Emergency", "test")
    assert alarms.update("Emergency", at(2)) is None  # still the same alarm
    assert alarms.update("OK", at(10)) is None  # not yet held off for 15 s
    cleared = alarms.update("OK", at(17.5))
    assert (cleared.type, cleared.alarm_uuid) == ("not_critical", issued.alarm_uuid)
    assert alarms.update("OK", at(40)) is None
    assert alarms.update("Emergency", at(41)).alarm_uuid != issued.alarm_uuid  # a new alarm


def test_an_emergency_within_the_hold_is_the_same_alarm():
    alarms = raiser(hold_s=15)
    alarms.update("Emergency", at(0))
    alarms.update("OK", at(10))
    assert alarms.update("Emergency", at(14)) is None
    assert alarms.update("OK", at(28)) is None  # 14 s after the last emergency
    assert alarms.update("OK", at(30)).type == "not_critical"


def test_alert_raises_nothing_by_default_but_can_be_configured():
    assert raiser().update("Alert", at(0)) is None
    assert raiser(alarm_on=("Alert", "Emergency")).update("Alert", at(0)).type == "init"


def test_reset_forgets_the_active_alarm():
    alarms = raiser()
    first = alarms.update("Emergency", at(0))
    alarms.reset()
    assert alarms.update("Emergency", at(1)).alarm_uuid != first.alarm_uuid
