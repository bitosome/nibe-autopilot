"""NIBE Autopilot: local, entity-backed supervisory control."""

from homeassistant.core import HomeAssistant

from .const import PLATFORMS
from .coordinator import AutopilotCoordinator


async def async_setup_entry(hass: HomeAssistant, entry):
    coordinator = AutopilotCoordinator(hass, entry)
    entry.runtime_data = coordinator
    await coordinator.async_initialize()
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await coordinator.async_stop()
        raise
    coordinator.async_start()
    entry.async_on_unload(entry.add_update_listener(async_options_updated))
    return True


async def async_options_updated(hass, entry):
    await entry.runtime_data.async_reconfigure()


async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_stop()
        return True
    return False
