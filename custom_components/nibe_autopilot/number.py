"""UI-editable, validated tuning. Values persist as config-entry options."""

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from .const import SETTINGS
from .entity import AutopilotEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [AutopilotNumber(entry.runtime_data, key, setting) for key, setting in SETTINGS.items()]
    )


class AutopilotNumber(AutopilotEntity, NumberEntity):
    def __init__(self, coordinator, key, setting):
        super().__init__(coordinator, key, setting.label)
        self._attr_native_min_value = setting.minimum
        self._attr_native_max_value = setting.maximum
        self._attr_native_step = setting.step
        self._attr_native_unit_of_measurement = setting.unit
        self._attr_mode = NumberMode.BOX
        self._attr_icon = "mdi:tune"
        if key not in ("comfort_target", "heater_cap", "heat_bias"):
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def native_value(self):
        return self.coordinator.config[self.key]

    @property
    def extra_state_attributes(self):
        return {"nibe_autopilot_control": self.key}

    async def async_set_native_value(self, value):
        try:
            await self.coordinator.async_change_settings({self.key: value})
        except (ValueError, TypeError) as exc:
            raise HomeAssistantError(str(exc)) from exc
