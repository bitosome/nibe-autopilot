"""Controller conditions are not assertions of physical safety."""

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import EntityCategory

from .entity import AutopilotEntity

SENSORS = {
    "warm_guard": "Warm-room guard",
    "global_hold": "Global fault hold",
    "condenser_hold": "Condenser space-heating hold",
    "mains_fresh": "Mains readings fresh",
    "heater_idle_stable": "Heater idle stable",
    "migration_ready": "Legacy state import ready",
}


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [AutopilotBinary(entry.runtime_data, key, name) for key, name in SENSORS.items()]
    )


class AutopilotBinary(AutopilotEntity, BinarySensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self):
        return bool((self.coordinator.data or {}).get(self.key))
