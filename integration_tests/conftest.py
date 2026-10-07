from copy import deepcopy

import pytest
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nibe_autopilot.const import DEFAULTS, DOMAIN, SOURCES
from custom_components.nibe_autopilot.engine import Reading, validate


@pytest.fixture(autouse=True)
def custom_components_enabled(enable_custom_integrations):
    yield


@pytest.fixture
def config():
    return validate(
        deepcopy(DEFAULTS)
        | {key: default for key, (_, _, default) in SOURCES.items()}
        | {
            "climates": [f"climate.room_{i}" for i in range(5)],
            "indoor_sensors": ["sensor.indoor"],
            "mains_sensors": [f"sensor.mains_{i}" for i in range(3)],
            "power_sensors": [f"sensor.power_{i}" for i in range(3)],
        }
    )


def fake_readings(config, now):
    def r(value, unit=None, **attributes):
        return Reading(
            str(value), now, attributes | ({"unit_of_measurement": unit} if unit else {})
        )

    states = {
        config["offset_entity"]: r(0, min=-10, max=10, step=1),
        config["heater_limit_entity"]: r(3, "kW", min=0, max=45, step=0.01),
        config["frequency_limit_entity"]: r(120, "Hz", min=17, max=120, step=1),
        config["mode_entity"]: r("AUTO"),
        config["priority_entity"]: r("HOT WATER"),
        config["alarm_entity"]: r(0),
        config["hot_gas_entity"]: r(60, "°C"),
        config["heater_power_entity"]: r(0, "kW"),
        config["fuse_entity"]: r(16, "A"),
        config["outdoor_entity"]: r(-15, "°C"),
        config["outdoor_fallback_entity"]: r(-14, "°C"),
        config["brine_entity"]: r(0, "°C"),
        "sensor.indoor": r(22, "°C"),
    }
    for entity_id in config["climates"]:
        states[entity_id] = r(
            "heat", temperature=22.5, current_temperature=21, hvac_action="heating"
        )
    for entity_id in config["mains_sensors"]:
        states[entity_id] = r(0, "A")
    for entity_id in config["power_sensors"]:
        states[entity_id] = r(250, "W")
    return states


@pytest.fixture
async def installed(hass, config, monkeypatch):
    pump = MockConfigEntry(domain="nibe_heatpump", title="Test pump")
    pump.add_to_hass(hass)
    entry = MockConfigEntry(domain=DOMAIN, title="NIBE Autopilot", data=config)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    for key, reg in zip(
        ("offset_entity", "heater_limit_entity", "frequency_limit_entity"),
        ("47011", "47212", "47104"),
        strict=True,
    ):
        registry.async_get_or_create(
            "number",
            "nibe_heatpump",
            f"test_{reg}",
            suggested_object_id=config[key].split(".")[1],
            config_entry=pump,
        )
    for entity_id, reading in fake_readings(config, dt_util.utcnow().timestamp()).items():
        hass.states.async_set(entity_id, reading.state, reading.attributes)
    calls = []

    async def write(call):
        calls.append(dict(call.data))
        state = hass.states.get(call.data["entity_id"])
        hass.states.async_set(state.entity_id, str(call.data["value"]), state.attributes)

    hass.services.async_register("number", "set_value", write)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    # The number platform registers its own service during setup. Wrap dispatch
    # after setup so real integration numbers work and only pump I/O is mocked.
    original_call = hass.services.async_call

    async def dispatch(_self, domain, service, service_data=None, **kwargs):
        if (
            domain == "number"
            and service == "set_value"
            and service_data.get("entity_id")
            in {
                config[key]
                for key in ("offset_entity", "heater_limit_entity", "frequency_limit_entity")
            }
        ):
            from types import SimpleNamespace

            await write(SimpleNamespace(data=service_data))
            return None
        return await original_call(domain, service, service_data, **kwargs)

    monkeypatch.setattr(type(hass.services), "async_call", dispatch)
    yield entry, calls
    await hass.config_entries.async_unload(entry.entry_id)
