"""Measured/derived controller telemetry, without unverified heat-output or COP."""

from datetime import datetime, timezone

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .entity import AutopilotEntity

SENSORS = {
    "status": ("Status", None),
    "indoor": ("Indoor temperature", "°C"),
    "ready_zones": ("Ready zone count", None),
    "demand_error": ("Room demand", "°C"),
    "electrical_allowance": ("Electrical allowance", "kW"),
    "circuit_power": ("Circuit input power", "kW"),
    "target_offset": ("Requested offset", None),
    "target_heater": ("Requested heater limit", "kW"),
    "target_frequency": ("Requested frequency cap", "Hz"),
    "global_until": ("Global hold until", None),
    "condenser_until": ("Condenser hold until", None),
}


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [
            AutopilotSensor(entry.runtime_data, key, *description)
            for key, description in SENSORS.items()
        ]
    )


class AutopilotSensor(AutopilotEntity, SensorEntity):
    def __init__(self, coordinator, key, name, unit):
        super().__init__(coordinator, key, name)
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = "mdi:heat-pump-outline"
        if key in ("global_until", "condenser_until"):
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
        elif key not in ("status",):
            self._attr_state_class = SensorStateClass.MEASUREMENT
        if key in ("circuit_power", "electrical_allowance", "target_heater"):
            self._attr_device_class = SensorDeviceClass.POWER
        if key not in ("indoor", "circuit_power", "status"):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        if self.key.endswith("_until"):
            stamp = data.get("memory", {}).get(self.key)
            return datetime.fromtimestamp(stamp, timezone.utc) if stamp else None
        return data.get(self.key)

    @property
    def extra_state_attributes(self):
        if self.key != "status":
            return None
        c = self.coordinator
        registry = er.async_get(self.hass)

        def find(domain, key):
            return registry.async_get_entity_id(domain, DOMAIN, f"{c.entry.entry_id}_{key}")

        mappings = {
            role: find(domain, key)
            for role, domain, key in [
                ("target", "number", "comfort_target"),
                ("heater_cap", "number", "heater_cap"),
                ("bias", "number", "heat_bias"),
                ("autopilot", "switch", "enabled"),
                ("indoor", "sensor", "indoor"),
                ("circuit_power", "sensor", "circuit_power"),
                ("allowance", "sensor", "electrical_allowance"),
                ("ready_zones", "sensor", "ready_zones"),
                ("warm_guard", "binary_sensor", "warm_guard"),
                ("cold_room_rescue", "binary_sensor", "cold_room_rescue"),
                ("mains_fresh", "binary_sensor", "mains_fresh"),
                ("global_hold", "sensor", "global_until"),
                ("condenser_hold", "sensor", "condenser_until"),
            ]
        }
        mappings.update(
            {
                role: c.config.get(key)
                for role, key in [
                    ("outdoor", "outdoor_entity"),
                    ("priority", "priority_entity"),
                    ("alarm", "alarm_entity"),
                    ("mode", "mode_entity"),
                    ("heater_permission", "heater_limit_entity"),
                    ("heater_power", "heater_power_entity"),
                    ("offset", "offset_entity"),
                    ("frequency_limit", "frequency_limit_entity"),
                    ("hot_gas", "hot_gas_entity"),
                    ("brine_in", "brine_entity"),
                ]
            }
        )
        data = c.data or {}
        return {
            key: data.get(key)
            for key in (
                "interlock",
                "error",
                "reasons",
                "migration_ready",
                "pending_writes",
                "unavailable_outputs",
                "cold_room_rescue",
                "cold_room_rescue_entities",
                "cold_room_pending_entities",
            )
        } | {
            "nibe_autopilot": True,
            "dashboard_entities": {k: v for k, v in mappings.items() if v},
            "room_entities": list(c.config["climates"]),
            "legacy_writers": sorted(c.legacy_entities()),
            "hygiene_cycle_success": "not_inferred",
            "ready_zones_are_flow_proof": False,
            "persistent_state": data.get("memory", {}),
        }
