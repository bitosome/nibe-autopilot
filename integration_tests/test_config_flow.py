from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import data_entry_flow
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nibe_autopilot.config_flow import GROUPS, fields, suggested
from custom_components.nibe_autopilot.const import DOMAIN, REQUIRED_SOURCES


async def test_full_setup_is_monitor_only_and_single_instance(hass, config):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {key: config[key] for key in REQUIRED_SOURCES}
    )
    assert result["step_id"] == "rooms"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {key: config[key] for key in ("climates", "indoor_sensors")}
    )
    assert result["step_id"] == "inputs"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"mains_sensors": config["mains_sensors"]}
    )
    assert result["step_id"] == "review"
    with patch(
        "custom_components.nibe_autopilot.async_setup_entry", new=AsyncMock(return_value=True)
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        await hass.async_block_till_done()
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"]["ownership_reviewed"] is False
    assert result["data"]["quiet_hz"] == 75
    again = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert again["reason"] == "single_instance_allowed"


async def test_setup_rejects_empty_rooms_on_the_room_page(hass, config):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {key: config[key] for key in REQUIRED_SOURCES}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"climates": [], "indoor_sensors": []}
    )
    assert result["step_id"] == "rooms"
    assert result["errors"] == {"base": "invalid_configuration"}


@pytest.mark.parametrize("group", GROUPS)
async def test_every_options_group_saves_and_preserves_other_settings(hass, config, group):
    entry = MockConfigEntry(domain=DOMAIN, data=config, options={"comfort_target": 23})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == data_entry_flow.FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": group}
    )
    assert result["step_id"] == group
    current = config | dict(entry.options)
    form = {
        str(key): current[str(key)] for key in fields(group, current).schema if str(key) in current
    }
    result = await hass.config_entries.options.async_configure(result["flow_id"], form)
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"]["comfort_target"] == 23
    assert result["data"]["heater_cap"] == 4


async def test_options_clear_optional_sources_and_set_room_override(hass, config):
    entry = MockConfigEntry(domain=DOMAIN, data=config)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "inputs"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"mains_sensors": config["mains_sensors"]}
    )
    assert result["data"]["outdoor_entity"] == ""
    assert result["data"]["power_sensors"] == []
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "room_sources"}
    )
    override = {config["climates"][0]: "sensor.room_override"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"room_sources": override}
    )
    assert result["data"]["room_sources"] == override


async def test_bad_threshold_rejected_and_live_bindings_locked(hass, installed):
    entry, _ = installed
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "zones"}
    )
    values = {str(key): entry.runtime_data.config[str(key)] for key in result["data_schema"].schema}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], values | {"zone_offset_0": 6}
    )
    assert result["errors"] == {"base": "invalid_configuration"}
    entry.runtime_data.enabled = True
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "rooms"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"climates": ["climate.other"], "indoor_sensors": ["sensor.indoor"]}
    )
    assert result["errors"] == {"base": "disable_first"}


def test_existing_helper_values_are_only_suggestions(hass):
    hass.states.async_set("input_number.indoor_target_temperature", "24")
    hass.states.async_set("climate.thermostat_controller_example", "off")
    values = suggested(hass)
    assert values["comfort_target"] == 24
    assert values["climates"] == ["climate.thermostat_controller_example"]
    assert values["ownership_reviewed"] is False
