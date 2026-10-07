from dataclasses import asdict

import pytest

from custom_components.nibe_autopilot.const import CRITICAL_ALARMS
from custom_components.nibe_autopilot.engine import Memory, Reading, Transient, evaluate, validate

from .conftest import fake_readings

NOW = 1800000000.0


def run(config, states=None, memory=None, transient=None, now=NOW, second=0):
    return evaluate(
        config,
        states or fake_readings(config, now),
        memory or Memory(),
        transient or Transient(),
        now,
        second,
    )


@pytest.mark.parametrize("alarm", [0, 181, 162, 163])
def test_dhw_keeps_bounded_assistance_and_full_frequency(config, alarm):
    states = fake_readings(config, NOW)
    states[config["alarm_entity"]].state = str(alarm)
    for key in config["climates"]:
        states[key].state = "off"
    decision = run(config, states, Memory(warm=True))
    assert decision.targets["heater_limit_entity"] == 3
    assert decision.targets["frequency_limit_entity"] == 120
    assert decision.memory.global_until == 0
    if alarm in (162, 163):
        assert decision.memory.condenser_until == NOW + 600
        assert decision.targets["offset_entity"] == -10


@pytest.mark.parametrize("alarm", sorted(CRITICAL_ALARMS))
def test_every_hard_fault_blocks_dhw(config, alarm):
    states = fake_readings(config, NOW)
    states[config["alarm_entity"]].state = str(alarm)
    d = run(config, states)
    assert d.targets["heater_limit_entity"] == 0
    assert d.memory.global_until == NOW + 600


def test_hotgas_and_condenser_holds_are_independent(config):
    states = fake_readings(config, NOW)
    states[config["alarm_entity"]].state = "162"
    states[config["hot_gas_entity"]].state = "115"
    d = run(config, states)
    assert d.memory.global_until == d.memory.condenser_until == NOW + 600
    assert d.targets["heater_limit_entity"] == 0


def test_condenser_dhw_off_transition_and_restart(config):
    states = fake_readings(config, NOW)
    states[config["alarm_entity"]].state = "162"
    first = run(config, states)
    states[config["priority_entity"]].state = "OFF"
    off = run(config, states, first.memory)
    assert off.memory.global_until == 0 and off.targets["heater_limit_entity"] == 0
    restored = Memory.restore(asdict(off.memory))
    states[config["alarm_entity"]].state = "0"
    states[config["priority_entity"]].state = "HOT WATER"
    assert run(config, states, restored).targets["heater_limit_entity"] == 3


@pytest.mark.parametrize("role", ["alarm_entity", "hot_gas_entity", "priority_entity"])
def test_stale_or_missing_data_blocks_dhw(config, role):
    states = fake_readings(config, NOW)
    states[config[role]].reported = NOW - 301
    assert run(config, states).targets["heater_limit_entity"] == 0
    states[config[role]].state = "unavailable"
    assert run(config, states).targets["heater_limit_entity"] == 0


@pytest.mark.parametrize("amps,cap", [(0, 4.5), (6, 1.5), (10, 0.5), (12, 0), (16, 0), (-1, 0)])
def test_unbalanced_stage_allowance(config, amps, cap):
    states = fake_readings(config, NOW)
    states[config["mains_sensors"][2]].state = str(amps)
    assert run(config, states).data["electrical_allowance"] == cap


def test_mains_stale_unit_wrong_and_unknown_fuse_fail_closed(config):
    for edit in ("stale", "unit", "fuse"):
        states = fake_readings(config, NOW)
        if edit == "stale":
            states[config["mains_sensors"][0]].reported = NOW - 121
        if edit == "unit":
            states[config["mains_sensors"][0]].attributes["unit_of_measurement"] = "W"
        if edit == "fuse":
            states[config["fuse_entity"]].state = "unknown"
        assert run(config, states).targets["heater_limit_entity"] == 0


def test_heater_increases_require_idle_and_cooldown(config):
    states = fake_readings(config, NOW)
    states[config["heater_limit_entity"]].state = "0"
    assert run(config, states).targets["heater_limit_entity"] == 0
    idle = Transient(heater_idle_since=NOW - 300)
    assert run(config, states, transient=idle).targets["heater_limit_entity"] == 3
    assert run(config, states, Memory(last_add=NOW - 599), idle).targets["heater_limit_entity"] == 0


def test_ready_zones_reset_after_restart_and_drop_immediately(config):
    states = fake_readings(config, NOW)
    states[config["priority_entity"]].state = "HEAT"
    t = Transient()
    assert run(config, states, transient=t).data["ready_zones"] == 0
    states = fake_readings(config, NOW + 481)
    states[config["priority_entity"]].state = "HEAT"
    assert run(config, states, transient=t, now=NOW + 481).data["ready_zones"] == 5
    states[config["climates"][0]].attributes["hvac_action"] = "idle"
    assert run(config, states, transient=t, now=NOW + 481).data["ready_zones"] == 4
    assert run(config, states, transient=Transient(), now=NOW + 481).data["ready_zones"] == 0


def test_each_zone_uses_its_own_target(config):
    states = fake_readings(config, NOW)
    for zone in config["climates"]:
        states[zone].attributes.update(temperature=22, current_temperature=22)
    states[config["climates"][0]].attributes.update(temperature=18, current_temperature=18)
    assert run(config, states).data["demand_error"] == 0


def test_room_override_and_unknown_zone(config):
    config["room_sources"] = {config["climates"][0]: "sensor.other_room"}
    states = fake_readings(config, NOW)
    assert not run(config, states).data["zones_ok"]
    states["sensor.other_room"] = Reading("21", NOW, {"unit_of_measurement": "°C"})
    assert run(config, states).data["zones_ok"]


def test_warm_hysteresis_and_recovery(config):
    states = fake_readings(config, NOW)
    states["sensor.indoor"].state = "23"
    first = run(config, states)
    assert first.memory.warm
    states["sensor.indoor"].state = "22.2"
    second = run(config, states, first.memory)
    assert not second.memory.warm and second.memory.recovery_until == NOW + 480
    assert second.data["warm_guard"]
    assert second.targets["heater_limit_entity"] == 3  # DHW bypass


def test_unknown_priority_releases_frequency_and_withholds_heater(config):
    states = fake_readings(config, NOW)
    states[config["priority_entity"]].state = "COOLING"
    d = run(config, states)
    assert d.targets["frequency_limit_entity"] == 120
    assert d.targets["heater_limit_entity"] == 0


def test_night_caps_never_apply_to_dhw_and_handle_non_wrapping_windows(config):
    states = fake_readings(config, NOW)
    t = Transient(zones_since={e: NOW - 500 for e in config["climates"]})
    assert run(config, states, transient=t).targets["frequency_limit_entity"] == 120
    states[config["priority_entity"]].state = "HEAT"
    assert run(config, states, transient=t).targets["frequency_limit_entity"] == 75
    assert (
        run(config, states, transient=t, second=12 * 3600).targets["frequency_limit_entity"] == 120
    )
    config.update(night_start="10:00", night_end="14:00")
    assert (
        run(config, states, transient=t, second=12 * 3600).targets["frequency_limit_entity"] == 75
    )


def test_power_units_and_unchanged_zero_phases(config):
    states = fake_readings(config, NOW)
    states[config["power_sensors"][0]] = Reading("0", NOW - 86400, {"unit_of_measurement": "W"})
    assert run(config, states).data["circuit_power"] == 0.5
    states[config["power_sensors"][1]] = Reading(".25", NOW, {"unit_of_measurement": "kW"})
    assert run(config, states).data["circuit_power"] == 0.5
    states[config["power_sensors"][1]].state = "unavailable"
    assert run(config, states).data["circuit_power"] is None


@pytest.mark.parametrize(
    "patch",
    [
        {"heater_cap": 7},
        {"reserve_a": 0},
        {"hot_gas_limit": 120},
        {"zone_offset_0": 6},
        {"night_start": "25:00"},
        {"pump_max_age": 999},
        {"ownership_reviewed": "yes"},
    ],
)
def test_invalid_settings_are_rejected(config, patch):
    with pytest.raises(ValueError):
        validate(config | patch)


def test_corrupt_holds_cannot_restore():
    for data in ({}, asdict(Memory()) | {"global_until": "bad"}, asdict(Memory()) | {"warm": 1}):
        with pytest.raises(ValueError):
            Memory.restore(data)
