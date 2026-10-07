"""Downloadable diagnostics omit household entity IDs and labels."""

from .const import SETTINGS


async def async_get_config_entry_diagnostics(hass, entry):
    c = entry.runtime_data
    return {
        "settings": {key: c.config[key] for key in SETTINGS},
        "enabled": c.enabled,
        "storage_error": c.storage_error,
        "status": {
            key: (c.data or {}).get(key)
            for key in (
                "status",
                "error",
                "interlock",
                "reasons",
                "ready_zones",
                "mains_fresh",
                "electrical_allowance",
                "sensors_ok",
                "zones_ok",
            )
        },
        "pending_output_roles": list(c.pending),
        "configured_room_count": len(c.config["climates"]),
        "limitations": [
            "No physical flow measurement",
            "No verified thermal metering",
            "Hygiene completion is not inferred",
            "Software is not breaker protection",
        ],
    }
