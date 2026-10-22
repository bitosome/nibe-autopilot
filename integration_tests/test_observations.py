"""Observation evidence must never become an actuator command or hygiene assertion."""

import pytest

from custom_components.nibe_autopilot.engine import Reading
from custom_components.nibe_autopilot.observations import Observations


def readings(now, priority="HEAT", actual=85, cap=75, bt6=48, target=55, alarm=0):
    return {
        key: Reading(str(value), now, {"unit_of_measurement": unit})
        for key, value, unit in (
            ("priority", priority, None),
            ("actual", actual, "Hz"),
            ("cap", cap, "Hz"),
            ("temperature", bt6, "°C"),
            ("stop", target, "°C"),
            ("alarm", alarm, None),
            ("periodic", "on", None),
        )
    }


def test_frequency_requires_settling_then_sustained_excess():
    o = Observations()
    for now in range(0, 900, 60):
        assert o.update(readings(now), now, 300, True)["frequency_limit_exceeded"] is False
    assert o.update(readings(900), 900, 300, True)["frequency_limit_exceeded"] is True
    assert o.update(readings(960, actual=77), 960, 300, True)["frequency_limit_exceeded"] is False


@pytest.mark.parametrize("change", ["dhw", "stale", "unit", "off", "gap", "cap"])
def test_frequency_cancels_evidence(change):
    o = Observations()
    for now in range(0, 901, 60):
        o.update(readings(now), now, 300, True)
    now = 960 if change != "gap" else 1300
    r = readings(now)
    if change == "dhw":
        r["priority"].state = "HOT WATER"
    if change == "stale":
        r["actual"].reported = 0
    if change == "unit":
        r["actual"].attributes["unit_of_measurement"] = "kHz"
    if change == "cap":
        r["cap"].state = "65"
    assert not o.update(r, now, 300, change != "off")["frequency_limit_exceeded"]


def cycle(o, bt6=55.2, alarm=0):
    o.update(readings(0), 0, 300, True)
    o.update(readings(60, priority="HOT WATER"), 60, 300, True)
    o.update(readings(120, priority="HOT WATER", bt6=bt6, alarm=alarm), 120, 300, True)
    return o.update(readings(180, priority="OFF", bt6=55.5), 180, 300, True)


def test_target_inference_not_pump_confirmation_and_preserved_after_normal_cycle():
    o = Observations()
    d = cycle(o)
    assert d["dhw_observation"] == "target_reached_inferred"
    assert o.last_target["target"] == 55
    o.update(readings(240, priority="HOT WATER"), 240, 300, True)
    o.update(readings(300, priority="OFF"), 300, 300, True)
    assert o.last["result"] == "target_not_observed"
    assert o.last_target["ended"] == 180


@pytest.mark.parametrize(
    "temp,alarm,result",
    [
        (54.9, 0, "target_not_observed"),
        (55.2, 181, "failed_alarm_181"),
        (55.2, 162, "target_reached_inferred"),
    ],
)
def test_completion_evidence(temp, alarm, result):
    assert cycle(Observations(), temp, alarm)["dhw_observation"] == result


@pytest.mark.parametrize("reason", ["startup", "missing", "target_change", "gap", "disabled"])
def test_incomplete_cycle_never_infers_success(reason):
    o = Observations()
    if reason != "startup":
        o.update(readings(0), 0, 300, True)
    o.update(readings(60, priority="HOT WATER"), 60, 300, True)
    r = readings(120, priority="HOT WATER", bt6=55.2)
    if reason == "missing":
        r.pop("temperature")
    if reason == "target_change":
        r["stop"].state = "54"
    if reason == "disabled":
        r["periodic"].state = "off"
    now = 500 if reason == "gap" else 120
    o.update(r, now, 300, True)
    d = o.update(readings(now + 60, priority="OFF", bt6=55.5), now + 60, 300, True)
    assert d["dhw_observation"] != "target_reached_inferred"


async def test_observation_record_survives_reload_without_resuming_cycle(hass, installed):
    entry, _ = installed
    c = entry.runtime_data
    cycle(c.observations)
    expected = dict(c.observations.last_target)
    await c.persist()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.observations.last_target == expected
    assert entry.runtime_data.observations.cycle is None
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", "nibe_autopilot", f"{entry.entry_id}_dhw_observation"
    )
    assert hass.states.get(entity_id).attributes["pump_confirmed_success"] is False


def test_late_failure_alarm_is_visible_without_a_tracked_cycle():
    o = Observations()
    cycle(o)
    d = o.update(readings(240, alarm=181), 240, 300, True)
    assert d["dhw_observation"] == "failed_alarm_181"


def test_legacy_rescue_exit_remains_valid(config):
    from custom_components.nibe_autopilot.engine import validate

    config.pop("room_rescue_mild_enter")
    config["room_rescue_exit"] = 0.8
    assert validate(config)["room_rescue_mild_enter"] == 0.9
