"""Explicit activation and optional night noise limit."""

from homeassistant.components.switch import SwitchEntity

from .entity import AutopilotEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [
            AutopilotSwitch(entry.runtime_data, "enabled", "Control enabled"),
            AutopilotSwitch(entry.runtime_data, "quiet_enabled", "Night quiet enabled"),
        ]
    )


class AutopilotSwitch(AutopilotEntity, SwitchEntity):
    _attr_icon = "mdi:heat-pump-outline"

    @property
    def is_on(self):
        return (
            self.coordinator.enabled if self.key == "enabled" else self.coordinator.config[self.key]
        )

    @property
    def extra_state_attributes(self):
        return {"nibe_autopilot_control": self.key}

    async def async_turn_on(self, **kwargs):
        await self._set(True)

    async def async_turn_off(self, **kwargs):
        await self._set(False)

    async def _set(self, value):
        if self.key == "enabled":
            await self.coordinator.async_set_enabled(value)
        else:
            await self.coordinator.async_change_settings({self.key: value})
