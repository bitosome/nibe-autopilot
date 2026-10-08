"""Warm-house/cold-room regression, with no physical pump I/O."""

from dataclasses import asdict

import pytest
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.nibe_autopilot.const import DOMAIN
from custom_components.nibe_autopilot.engine import Memory, Reading, Transient, evaluate, validate

from .conftest import fake_readings

NOW = 1800000000.0


def readings(config, now=NOW):
    states = fake_readings(config, now)
    states[config["priority_entity"]].state = "HEATING"
    states["sensor.indoor"].state = "23.5"
    states[config["offset_entity"]].state = "-10"
    return states


def decide(config, transient, now=NOW, states=None, memory=None):
    return evaluate(config, states or readings(config, now), memory or Memory(), transient, now, 0)


def qualified(config):
    t = Transient(zones_since={e: NOW - 480 for e in config["climates"]})
    decide(config, t)
    d = decide(config, t, NOW + 1200)
    assert d.data["cold_room_rescue"]
    return t, d


def test_ready_room_requires_its_own_continuous_delay(config):
    t = Transient()
    assert not decide(config, t).data["cold_room_rescue"]
    assert not t.cold_since
    assert not decide(config, t, NOW + 480).data["cold_room_rescue"]
    assert set(t.cold_since.values()) == {NOW + 480}
    assert not decide(config, t, NOW + 1679).data["cold_room_rescue"]
    d = decide(config, t, NOW + 1680)
    assert d.data["cold_room_rescue"] and d.memory.warm and d.data["warm_guard"]
    assert d.targets["offset_entity"] == -9
    assert d.targets["heater_limit_entity"] == 0
    assert d.targets["frequency_limit_entity"] == 75


@pytest.mark.parametrize("count,ceiling", [(1, -2), (2, 0), (3, 0), (5, 0)])
def test_rescue_keeps_zone_and_absolute_ceiling(config, count, ceiling):
    config["climates"] = config["climates"][:count]
    config["heat_bias"] = 3
    t, d = qualified(config)
    states = readings(config, NOW + 1200)
    states[config["offset_entity"]].state = str(ceiling - 1)
    assert decide(config, t, NOW + 1200, states).targets["offset_entity"] == ceiling
    states[config["offset_entity"]].state = "4"
    d = decide(config, t, NOW + 1200, states, Memory(last_offset=NOW + 1200))
    assert d.targets["offset_entity"] == ceiling  # protective decrease ignores cooldown


def test_rescue_ramp_obeys_persisted_cooldown(config):
    t, d = qualified(config)
    memory = Memory.restore(asdict(d.memory))
    memory.last_offset = NOW + 1199
    assert "offset_entity" not in decide(config, t, NOW + 1200, memory=memory).targets
    assert decide(config, t, NOW + 1799, memory=memory).targets["offset_entity"] == -9


def test_hysteresis_stops_on_own_room_exit_without_clearing_warm_hold(config):
    t, d = qualified(config)
    states = readings(config, NOW + 1201)
    for e in config["climates"]:
        states[e].attributes.update(temperature=23, current_temperature=22.5)
    assert decide(config, t, NOW + 1201, states, d.memory).data["cold_room_rescue"]
    for e in config["climates"]:
        states[e].attributes["current_temperature"] = 22.7
    states[config["offset_entity"]].state = "0"
    d.memory.last_offset = NOW + 1201
    d = decide(config, t, NOW + 1201, states, d.memory)
    assert not d.data["cold_room_rescue"] and d.memory.warm
    assert not t.cold_since and not t.rescue_rooms
    assert d.targets["offset_entity"] == -6


def test_qualification_resets_below_entry_and_is_not_shared_across_rooms(config):
    t = Transient(zones_since={e: NOW - 480 for e in config["climates"]})
    states = readings(config)
    for e in config["climates"]:
        states[e].attributes.update(temperature=18, current_temperature=18)
    a, b = config["climates"][:2]
    states[a].attributes["current_temperature"] = 17
    decide(config, t, states=states)
    for r in states.values():
        r.reported = NOW + 1199
    states[a].attributes["current_temperature"] = 17.1
    states[b].attributes["current_temperature"] = 17
    assert not decide(config, t, NOW + 1199, states).data["cold_room_rescue"]
    assert a not in t.cold_since and t.cold_since[b] == NOW + 1199


@pytest.mark.parametrize(
    "condition",
    [
        "global",
        "condenser",
        "hotgas",
        "recovery",
        "unknown_priority",
        "stale_priority",
        "stale_indoor",
        "missing_alarm",
        "unknown_zone",
        "all_idle",
        "all_off",
        "override",
    ],
)
def test_safety_or_lost_demand_cancels_rescue_and_its_evidence(config, condition):
    t, d = qualified(config)
    now = NOW + 1201
    states = readings(config, now)
    memory = d.memory
    if condition == "global":
        memory.global_until = now + 600
    elif condition == "condenser":
        memory.condenser_until = now + 600
    elif condition == "hotgas":
        states[config["hot_gas_entity"]].state = "115"
    elif condition == "recovery":
        memory.recovery_until = now + 480
    elif condition == "unknown_priority":
        states[config["priority_entity"]].state = "COOLING"
    elif condition == "stale_priority":
        states[config["priority_entity"]].reported = now - 301
    elif condition == "stale_indoor":
        states["sensor.indoor"].reported = now - 301
    elif condition == "missing_alarm":
        states[config["alarm_entity"]].state = "unavailable"
    elif condition == "unknown_zone":
        states[config["climates"][0]].state = "unavailable"
    elif condition in ("all_idle", "all_off"):
        for e in config["climates"]:
            states[e].attributes["hvac_action"] = "idle"
            if condition == "all_off":
                states[e].state = "off"
    elif condition == "override":
        config["room_sources"] = {config["climates"][0]: "sensor.override"}
        states["sensor.override"] = Reading("20", now - 301, {"unit_of_measurement": "°C"})
    d = decide(config, t, now, states, memory)
    assert not d.data["cold_room_rescue"]
    assert not t.cold_since and not t.rescue_rooms
    assert d.targets.get("offset_entity", -10) <= -6
    assert d.targets["heater_limit_entity"] == 0


@pytest.mark.parametrize("alarm,heater", [(0, 3), (181, 3), (162, 3), (163, 3), (150, 0)])
def test_dhw_preempts_rescue_without_losing_existing_assistance(config, alarm, heater):
    t, d = qualified(config)
    states = readings(config, NOW + 1201)
    states[config["priority_entity"]].state = "HOT WATER"
    states[config["alarm_entity"]].state = str(alarm)
    d = decide(config, t, NOW + 1201, states, d.memory)
    assert not d.data["cold_room_rescue"] and not t.cold_since
    assert d.targets["heater_limit_entity"] == heater
    assert d.targets["frequency_limit_entity"] == 120


def test_restart_keeps_durable_holds_but_restarts_rescue_evidence(config):
    _, d = qualified(config)
    restored = Memory.restore(asdict(d.memory))
    assert restored.warm
    assert not decide(config, Transient(), NOW + 1201, memory=restored).data["cold_room_rescue"]


def test_old_config_gets_bounded_presets_and_invalid_thresholds_are_rejected(config):
    old = {k: v for k, v in config.items() if not k.startswith("room_rescue_")}
    assert validate(old)["room_rescue_seconds"] == 1200
    for patch in ({"room_rescue_offset": 1}, {"room_rescue_enter": 0.5, "room_rescue_exit": 0.5}):
        with pytest.raises(ValueError):
            validate(config | patch)


async def test_new_entities_and_tuning_reset_only_rescue_evidence(hass, installed):
    entry, _ = installed
    c = entry.runtime_data
    registry = er.async_get(hass)
    rescue_id = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry.entry_id}_cold_room_rescue"
    )
    assert hass.states.get(rescue_id).state == "off"
    number_id = registry.async_get_entity_id(
        "number", DOMAIN, f"{entry.entry_id}_room_rescue_enter"
    )
    assert hass.states.get(number_id).state == "1.0"
    priority = hass.states.get(c.config["priority_entity"])
    hass.states.async_set(priority.entity_id, "HEATING", priority.attributes)
    indoor = hass.states.get("sensor.indoor")
    hass.states.async_set(indoor.entity_id, "23.5", indoor.attributes)
    await hass.async_block_till_done()
    now = dt_util.utcnow().timestamp()
    c.transient.zones_since = {c.config["climates"][0]: now - 1000}
    c.transient.heater_idle_since = now - 300
    c.transient.cold_since = {c.config["climates"][0]: now - 100}
    c.transient.rescue_rooms.add(c.config["climates"][0])
    await hass.services.async_call(
        "number", "set_value", {"entity_id": number_id, "value": 1.2}, blocking=True
    )
    await hass.async_block_till_done()
    assert not c.transient.rescue_rooms
    assert c.transient.cold_since[c.config["climates"][0]] >= now
    assert c.transient.zones_since[c.config["climates"][0]] == now - 1000
    assert c.transient.heater_idle_since == now - 300
