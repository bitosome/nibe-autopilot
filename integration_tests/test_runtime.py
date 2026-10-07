from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.nibe_autopilot.const import DOMAIN, LEGACY_HOLDS


async def enable(hass, entry):
    c = entry.runtime_data
    await c.async_change_settings({"ownership_reviewed": True})
    await hass.async_block_till_done()
    await c.async_set_enabled(True)
    await hass.async_block_till_done()


async def test_setup_has_presets_native_entities_and_no_writes(hass, installed):
    entry, calls = installed
    c = entry.runtime_data
    assert c.data["status"] == "monitor" and not c.enabled
    assert calls == []
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_comfort_target")
    assert hass.states.get(entity_id).state == "22.5"
    status_id = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_status")
    await c.async_refresh()
    assert hass.states.get(status_id).attributes["dashboard_entities"]["target"] == entity_id


async def test_takeover_requires_explicit_review_and_legacy_writers_off(hass, installed):
    entry, calls = installed
    c = entry.runtime_data
    with pytest.raises(HomeAssistantError, match="ownership_not_reviewed"):
        await c.async_set_enabled(True)
    hass.states.async_set("automation.nibe_autopilot", "on")
    await c.async_change_settings({"ownership_reviewed": True})
    await hass.async_block_till_done()
    with pytest.raises(HomeAssistantError, match="legacy_writer"):
        await c.async_set_enabled(True)
    assert calls == []
    hass.states.async_set("automation.nibe_autopilot", "off")
    await c.async_set_enabled(True)
    assert c.enabled


async def test_manual_mode_never_changed_or_controlled(hass, installed):
    entry, calls = installed
    c = entry.runtime_data
    s = hass.states.get(c.config["mode_entity"])
    hass.states.async_set(s.entity_id, "MANUAL", s.attributes)
    await c.async_change_settings({"ownership_reviewed": True})
    await hass.async_block_till_done()
    with pytest.raises(HomeAssistantError, match="auto"):
        await c.async_set_enabled(True)
    assert calls == []


async def test_ownership_loss_latches_control_off(hass, installed):
    entry, calls = installed
    await enable(hass, entry)
    calls.clear()
    hass.states.async_set("automation.nibe_night_quiet_mode", "on")
    await entry.runtime_data.async_refresh()
    assert not entry.runtime_data.enabled
    assert entry.runtime_data.error == "legacy_writer_active_or_unavailable"
    assert calls == []


async def test_imported_holds_are_never_shortened(hass, installed):
    entry, _ = installed
    c = entry.runtime_data
    now = dt_util.utcnow().timestamp()
    for key, entity_id in LEGACY_HOLDS.items():
        stamp = now + 900 if key == "global_until" else now
        hass.states.async_set(entity_id, "2026-10-07 23:00:00", {"timestamp": stamp})
    hass.states.async_set("input_boolean.nibe_warm_room_guard", "on")
    await enable(hass, entry)
    assert c.memory.global_until >= now + 900
    assert c.data["target_heater"] == 0


async def test_incomplete_legacy_state_prevents_takeover(hass, installed):
    entry, calls = installed
    c = entry.runtime_data
    hass.states.async_set("input_datetime.nibe_overheat_until", "unavailable")
    await c.async_change_settings({"ownership_reviewed": True})
    await hass.async_block_till_done()
    with pytest.raises(HomeAssistantError, match="incomplete"):
        await c.async_set_enabled(True)
    assert calls == []


async def test_native_number_changes_preserve_other_options_and_readiness(hass, installed):
    entry, _ = installed
    c = entry.runtime_data
    c.transient.zones_since = {c.config["climates"][0]: dt_util.utcnow().timestamp() - 400}
    before = c.transient.zones_since.copy()
    registry = er.async_get(hass)
    number_id = registry.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_comfort_target")
    # Native platform registered its own service after setup, so call it normally.
    await hass.services.async_call(
        "number", "set_value", {"entity_id": number_id, "value": 23}, blocking=True
    )
    await hass.async_block_till_done()
    assert c.config["comfort_target"] == 23
    assert entry.options["comfort_target"] == 23
    assert c.transient.zones_since[c.config["climates"][0]] == before[c.config["climates"][0]]


async def test_invalid_ui_tuning_rejected_server_side(hass, installed):
    entry, _ = installed
    with pytest.raises(ValueError):
        await entry.runtime_data.async_change_settings({"hot_gas_limit": 125})


async def test_service_failure_stops_other_writes(hass, installed, monkeypatch):
    entry, calls = installed
    await enable(hass, entry)
    c = entry.runtime_data

    async def fail(call):
        calls.append(dict(call.data))
        raise HomeAssistantError("Synthetic failure")

    async def fail_dispatch(_self, domain, service, service_data=None, **kwargs):
        from types import SimpleNamespace

        await fail(SimpleNamespace(data=service_data))

    monkeypatch.setattr(type(hass.services), "async_call", fail_dispatch)
    c.pending.clear()
    calls.clear()
    hass.states.async_set(c.config["alarm_entity"], "50")
    await c.async_refresh()
    assert not c.enabled
    assert len(calls) == 1
    assert calls[0]["entity_id"] == c.config["heater_limit_entity"]


async def test_storage_failure_blocks_every_output(hass, installed):
    entry, calls = installed
    c = entry.runtime_data
    c.store.async_save = AsyncMock(side_effect=OSError("storage failed"))
    c.config["ownership_reviewed"] = True
    with pytest.raises(HomeAssistantError, match="storage"):
        await c.async_set_enabled(True)
    assert not c.enabled and c.storage_error and not calls


async def test_fault_during_storage_await_cancels_heater_increase(hass, installed):
    entry, calls = installed
    c = entry.runtime_data
    await enable(hass, entry)
    now = dt_util.utcnow().timestamp()
    original = c.persist

    async def save_then_alarm():
        await original()
        if c.memory.last_add >= now:
            hass.states.async_set(c.config["alarm_entity"], "50")

    c.persist = save_then_alarm
    async with c.lock:
        calls.clear()
        c.pending.clear()
        c.memory.last_add = now - 1200
        c.transient.heater_idle_since = now - 600
        output = hass.states.get(c.config["heater_limit_entity"])
        hass.states.async_set(output.entity_id, "0", output.attributes)
        await c._write("heater_limit_entity", 3)
    assert calls == []
    assert c.memory.global_until > now


async def test_dhw_transition_cancels_pending_space_frequency_command(hass, installed):
    entry, calls = installed
    c = entry.runtime_data
    await enable(hass, entry)
    original = c.persist

    async def persist_then_dhw():
        await original()
        hass.states.async_set(c.config["priority_entity"], "HOT WATER")

    c.persist = persist_then_dhw
    async with c.lock:
        calls.clear()
        c.pending.clear()
        hass.states.async_set(c.config["priority_entity"], "HEAT")
        await c._write("frequency_limit_entity", 50)
    assert calls == []


async def test_restart_restores_holds_but_restarts_actuator_delays(hass, installed):
    entry, calls = installed
    c = entry.runtime_data
    await enable(hass, entry)
    now = dt_util.utcnow().timestamp()
    c.memory.global_until = now + 1800
    c.memory.condenser_until = now + 1200
    c.transient.zones_since = {room: now - 900 for room in c.config["climates"]}
    await c.persist()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    fresh = entry.runtime_data
    assert fresh.enabled
    assert fresh.memory.global_until >= now + 1800
    assert fresh.memory.condenser_until >= now + 1200
    assert fresh.data["ready_zones"] == 0


async def test_unconfirmed_write_times_out_without_retry_storm(hass, installed):
    entry, calls = installed
    c = entry.runtime_data
    await enable(hass, entry)
    calls.clear()
    c.pending["frequency_limit_entity"] = (50, dt_util.utcnow().timestamp() - 1)
    hass.states.async_set(c.config["priority_entity"], "HEAT")
    await c.async_refresh()
    assert not c.enabled and c.error.startswith("write_failed")
    assert all(call == {"entity_id": c.config["heater_limit_entity"], "value": 0} for call in calls)


async def test_protective_frequency_decrease_supersedes_pending_release(hass, installed):
    entry, calls = installed
    c = entry.runtime_data
    await enable(hass, entry)
    async with c.lock:
        calls.clear()
        hass.states.async_set(c.config["priority_entity"], "HEAT")
        output = hass.states.get(c.config["frequency_limit_entity"])
        hass.states.async_set(output.entity_id, "85", output.attributes)
        c.pending["frequency_limit_entity"] = (120, dt_util.utcnow().timestamp() + 300)
        await c._write("frequency_limit_entity", 50)
    assert calls == [{"entity_id": c.config["frequency_limit_entity"], "value": 50}]


async def test_concurrent_tuning_validates_latest_options_not_stale_runtime(hass, installed):
    entry, _ = installed
    c = entry.runtime_data
    await c.async_change_settings({"brine_cold": 3})
    with pytest.raises(ValueError, match="Inconsistent"):
        await c.async_change_settings({"brine_mild": 2})


async def test_unavailable_output_is_visible_and_other_protective_writes_continue(hass, installed):
    entry, calls = installed
    c = entry.runtime_data
    await enable(hass, entry)
    hass.states.async_set(c.config["frequency_limit_entity"], "unavailable")
    hass.states.async_set(c.config["alarm_entity"], "50")
    await c.async_refresh()
    assert c.data["status"] == "blocked"
    assert "frequency_limit_entity" in c.data["unavailable_outputs"]
    assert any(call == {"entity_id": c.config["heater_limit_entity"], "value": 0} for call in calls)


async def test_corrupt_persistent_holds_fail_closed_on_reload(hass, installed):
    entry, calls = installed
    c = entry.runtime_data
    await enable(hass, entry)
    await hass.config_entries.async_unload(entry.entry_id)
    await c.store.async_save(
        {"enabled": True, "memory": {"warm": False, "global_until": "invalid"}}
    )
    calls.clear()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.storage_error
    assert entry.runtime_data.enabled is False
    assert entry.runtime_data.data["status"] == "blocked"
    assert calls == []
