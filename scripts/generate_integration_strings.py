"""Generate native configuration labels from the single settings catalog."""

import json
from pathlib import Path

from custom_components.nibe_autopilot.config_flow import GROUPS, fields
from custom_components.nibe_autopilot.const import DEFAULTS, SETTINGS, SOURCES

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "nibe_autopilot"
LABELS = (
    {key: setting.label for key, setting in SETTINGS.items()}
    | {key: label for key, (label, _, _) in SOURCES.items()}
    | {
        "climates": "Room thermostats (ESPHome or standard HA climate entities)",
        "indoor_sensors": "Indoor temperature inputs (mean; all must be available)",
        "mains_sensors": "Whole-house phase currents (exactly three, including EV and heat pump)",
        "power_sensors": "Heat-pump circuit power inputs (sum; W or kW)",
        "room_sources": "Optional current-temperature override for each thermostat",
        "legacy_writers": "Other automations that write the pump control registers",
        "ownership_reviewed": "I have reviewed every controller and will disable all other writers before enabling control",
        "quiet_enabled": "Enable night frequency limiting for space heating only",
        "night_start": "Quiet period starts",
        "night_end": "Quiet period ends",
    }
)
TITLES = {
    "pump": "NIBE pump entities",
    "rooms": "Rooms and indoor temperature",
    "room_sources": "Room temperature overrides",
    "inputs": "Electrical and source sensors",
    "comfort": "Everyday comfort",
    "heating": "Heating response and warm guard",
    "zones": "Ready-zone ceilings",
    "quiet": "Night quiet mode",
    "electrical": "Electric heater limits",
    "safety": "Protection and freshness",
    "ownership": "Controller ownership and migration",
}
DESCRIPTIONS = {
    "pump": "Validated profile: F1255-6, 3x400 V, Auto mode. Keep the existing NIBE Heat Pump/NibeGW integration. Only offset 47011, heater limit 47212 and frequency cap 47104 can be written; operating mode is read-only. Installation starts in monitor mode and never enables entities or edits the pump.",
    "rooms": "Each heat/off thermostat uses its own target and current_temperature, including ESPHome thermostats. Suggested existing thermostat-controller zones must be reviewed. Room relay demand and the opening delay are NOT proof of valve position or water flow. Sensor inputs may come from any integration, with Celsius or Fahrenheit metadata.",
    "room_sources": "Leave a room blank to use its climate.current_temperature. An override can be any temperature sensor (including an ESPHome sensor). Its freshness is checked. This does not inject room temperatures into NIBE or change the thermostat's own sensor.",
    "inputs": "Select all three house-input current phases in amperes, not just the pump or EV circuits. Optional circuit power can be one dedicated power meter or three phase power sensors; these are summed with W/kW conversion. They are not used as electrical headroom. No produced heat or COP is fabricated.",
    "comfort": "Defaults follow the existing controller. The house target is only the warm guard/night comfort reference; each room keeps its own target. Heater allowance is permission, not actual consumption. Manual heat trim is not automatically integrated.",
    "heating": "Slow underfloor actuators require a conservative opening allowance (default eight minutes). While the house warm guard remains latched, a ready room at least 1 C below its own target for another 20 minutes can permit limited offset recovery. Rescue ends at a 0.3 C deficit or loss of valid ready demand; exit must be below entry. It ramps one step per interval, never above zero or the ready-zone ceiling, and never permits electric space heat through the warm guard. Fault/recovery holds, DHW and invalid inputs cancel rescue evidence; restart and rescue-tuning changes restart it. This is not hydraulic protection. Offset alone cannot stop heating when minimum supply binds.",
    "zones": "Ceilings must increase or stay equal as more zones become ready. The fifth entry means five or more zones. These are heuristics, not flow measurements. DHW always bypasses these frequency caps.",
    "quiet": "Defaults: 22:30 to 06:30, 75 Hz, comfort rescue at a 0.7 C deficit. Equal start/end disables the time window. DHW or unrecognized/stale priority always releases the HA cap to 120 Hz. Firmware exclusions still apply. No DHW circulation or high-power setting is changed.",
    "electrical": "Validated, conservative unbalanced heater-stage allowance: external fuse bound up to 16 A with at least 2 A reserve. Existing heater current is NOT subtracted from mains readings. Increasing allowance requires fresh actual heater-idle readings and a cooldown. Software is not breaker protection; verify CTs and hardware protection physically.",
    "safety": "Condenser codes 162/163 hold space heating only; confirmed DHW retains otherwise-permitted assistance. Global fault codes and hot gas block DHW addition too. These guards cannot be disabled through the UI. Alarm 181 is reported, never reset or treated as proof of a later successful hygiene cycle.",
    "ownership": "Stop the integration before changing source mappings. Turn off the legacy main, warm guard and compressor governor together before activation. The integration checks known and configured writers on each write, but cannot discover every external controller or templated script. Existing hold/cooldown helpers are read and merged, never cleared. Then explicitly turn on Control enabled. No migration action disables your automations automatically.",
}
ERRORS = {
    "invalid_configuration": "Invalid mapping or setting. Select at least one room and indoor sensor, exactly three distinct current phases, valid source domains, nondecreasing zone caps and values within their documented bounds. Cold-room rescue exit must be below entry.",
    "disable_first": "Turn off Control enabled before changing entity mappings or ownership.",
}
steps = {
    group: {
        "title": TITLES[group],
        "description": DESCRIPTIONS[group],
        "data": {str(key): LABELS[str(key)] for key in fields(group, DEFAULTS).schema},
    }
    for group in GROUPS
}
config_steps = {
    "user": steps["pump"],
    "rooms": steps["rooms"],
    "inputs": steps["inputs"],
    "review": {
        "title": "Create a monitor-only controller",
        "description": "The controller will be created with the current F1255 tuning: 22.5 C reference (or your existing helper value), room-aware demand, 8-minute actuator delay, warm guard, fault holds, conservative three-phase heater allowance and night limits. Your existing settings and automations are NOT changed. Review all settings under Configure, compare monitor targets with the running automations, then perform the documented explicit handover. A successful periodic hygiene cycle remains unverified by this software.",
    },
}
document = {
    "title": "NIBE Autopilot",
    "config": {
        "step": config_steps,
        "error": ERRORS,
        "abort": {
            "single_instance_allowed": "Only one NIBE Autopilot controller may be configured."
        },
    },
    "options": {
        "step": {
            "init": {"title": "NIBE Autopilot configuration", "menu_options": TITLES},
            **steps,
        },
        "error": ERRORS,
    },
}
for filename in ("strings.json", "translations/en.json"):
    (ROOT / filename).write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
