"""Validated F1255-6 3x400 V profile; no direct transport or cloud control."""

from dataclasses import dataclass

DOMAIN = "nibe_autopilot"
PLATFORMS = ["sensor", "binary_sensor", "number", "switch"]
VERSION = "0.1.1"
OUTPUTS = ("offset_entity", "heater_limit_entity", "frequency_limit_entity")
CRITICAL_ALARMS = frozenset(
    [
        40,
        41,
        42,
        43,
        44,
        45,
        50,
        54,
        55,
        56,
        57,
        150,
        155,
        439,
        441,
        443,
        445,
        447,
        449,
        452,
        453,
        455,
        460,
        461,
    ]
)
CONDENSER_ALARMS = frozenset([162, 163])
STAGES = (
    (0.5, 2.2),
    (1, 4.3),
    (1.5, 4.3),
    (2, 8.7),
    (2.5, 8.7),
    (3, 8.7),
    (3.5, 8.7),
    (4, 8.7),
    (4.5, 9.7),
    (5, 16.2),
    (5.5, 16.2),
    (6, 16.2),
)
LEGACY_WRITERS = (
    "automation.nibe_autopilot",
    "automation.nibe_autopilot_guard",
    "automation.nibe_night_quiet_mode",
)
LEGACY_IDS = frozenset(["1759311286123", "1759322716707", "1770749427596"])
LEGACY_HOLDS = {
    "global_until": "input_datetime.nibe_overheat_until",
    "condenser_until": "input_datetime.nibe_condenser_hold_until",
    "recovery_until": "input_datetime.nibe_guard_release_until",
    "last_offset": "input_datetime.nibe_last_offset_change",
    "last_add": "input_datetime.nibe_last_add_change",
}

# A familiar suggestion is preselected only when it actually exists in HA.
SOURCES = {
    "offset_entity": ("Heating curve offset", "number", "number.heat_offset_s1_47011"),
    "heater_limit_entity": ("Internal heater limit", "number", "number.max_int_add_power_47212"),
    "frequency_limit_entity": ("Compressor frequency cap", "number", "number.max_comp_freq_47104"),
    "mode_entity": ("Operating mode (read only)", "select", "select.operational_mode_47137"),
    "priority_entity": ("Operating priority", "sensor", "sensor.prio_43086"),
    "alarm_entity": ("Alarm code", "sensor", "sensor.alarm_45001"),
    "hot_gas_entity": (
        "Discharge temperature BT14",
        "sensor",
        "sensor.eb100_ep14_bt14_hot_gas_temp_40018",
    ),
    "heater_power_entity": (
        "Actual internal heater power",
        "sensor",
        "sensor.int_el_add_power_43084",
    ),
    "fuse_entity": ("NIBE fuse setting", "number", "number.fuse_47214"),
    "outdoor_entity": (
        "Outdoor temperature",
        "sensor",
        "sensor.ecowitt_ws90_1_outdoor_temperature",
    ),
    "outdoor_fallback_entity": (
        "Outdoor fallback BT1",
        "sensor",
        "sensor.bt1_outdoor_temperature_40004",
    ),
    "brine_entity": ("Brine inlet BT10", "sensor", "sensor.eb100_ep14_bt10_brine_in_temp_40015"),
}
REQUIRED_SOURCES = tuple(
    key
    for key in SOURCES
    if key not in ("outdoor_entity", "outdoor_fallback_entity", "brine_entity")
)


@dataclass(frozen=True)
class Setting:
    label: str
    default: float
    minimum: float
    maximum: float
    step: float
    group: str
    unit: str | None = None


SETTINGS = {
    "comfort_target": Setting("House comfort target", 22.5, 18, 30, 0.5, "comfort", "°C"),
    "heater_cap": Setting("User heater allowance", 4, 0, 6, 0.5, "comfort", "kW"),
    "heat_bias": Setting("Manual heating trim", 0, -3, 3, 0.5, "comfort"),
    "kp": Setting("Proportional gain", 1.5, 0.1, 3, 0.1, "heating"),
    "warm_enter": Setting("Warm guard entry above target", 0.4, 0.1, 2, 0.1, "heating", "°C"),
    "warm_exit": Setting("Warm guard exit below target", 0.3, 0.1, 2, 0.1, "heating", "°C"),
    "room_rescue_enter": Setting("Cold-room rescue entry deficit", 1, 0.5, 2, 0.1, "heating", "°C"),
    "room_rescue_exit": Setting(
        "Cold-room rescue exit deficit", 0.3, 0.1, 0.9, 0.1, "heating", "°C"
    ),
    "room_rescue_seconds": Setting(
        "Sustained cold-room delay", 1200, 600, 3600, 60, "heating", "s"
    ),
    "room_rescue_offset": Setting("Cold-room rescue offset ceiling", 0, -4, 0, 1, "heating"),
    "recovery_seconds": Setting("Warm guard recovery delay", 480, 60, 1800, 60, "heating", "s"),
    "offset_interval": Setting("Offset ramp interval", 600, 600, 3600, 60, "heating", "s"),
    "zone_delay": Setting("Actuator opening allowance", 480, 60, 1800, 60, "heating", "s"),
    "brine_cold": Setting("Cold brine threshold", 1, -5, 3, 0.5, "heating", "°C"),
    "brine_mild": Setting("Mild brine threshold", 3, 0, 6, 0.5, "heating", "°C"),
    "outdoor_cold": Setting("Cold outdoor threshold", -10, -30, 0, 1, "heating", "°C"),
    "quiet_hz": Setting("Night compressor limit", 75, 40, 120, 1, "quiet", "Hz"),
    "comfort_rescue": Setting("Night comfort deficit override", 0.7, 0.1, 2, 0.1, "quiet", "°C"),
    "breaker_a": Setting("External main-breaker bound", 16, 6, 16, 1, "electrical", "A"),
    "reserve_a": Setting("Per-phase reserve", 2, 2, 6, 0.5, "electrical", "A"),
    "dhw_permission": Setting("DHW heater permission ceiling", 3, 0, 3, 0.5, "electrical", "kW"),
    "heater_idle_seconds": Setting(
        "Heater idle before increase", 300, 300, 1800, 60, "electrical", "s"
    ),
    "heater_interval": Setting(
        "Heater cap increase cooldown", 600, 600, 3600, 60, "electrical", "s"
    ),
    "pump_max_age": Setting("Pump/indoor maximum report age", 300, 30, 300, 10, "safety", "s"),
    "mains_max_age": Setting("Mains maximum report age", 120, 30, 120, 10, "safety", "s"),
    "fault_hold_seconds": Setting("Fault hold duration", 600, 600, 3600, 60, "safety", "s"),
    "hot_gas_limit": Setting("Discharge temperature guard", 115, 100, 115, 1, "safety", "°C"),
}
for count, offset, hz in zip(
    range(6), [-4, -2, 0, 2, 4, 6], [50, 55, 65, 85, 100, 120], strict=True
):
    SETTINGS[f"zone_offset_{count}"] = Setting(
        f"Offset ceiling: {count}{'+' if count == 5 else ''} ready zones", offset, -6, 6, 1, "zones"
    )
    SETTINGS[f"zone_hz_{count}"] = Setting(
        f"Frequency ceiling: {count}{'+' if count == 5 else ''} ready zones",
        hz,
        17,
        120,
        1,
        "zones",
        "Hz",
    )

DEFAULTS = {key: value.default for key, value in SETTINGS.items()} | {
    "quiet_enabled": True,
    "night_start": "22:30:00",
    "night_end": "06:30:00",
    "ownership_reviewed": False,
    "climates": [],
    "indoor_sensors": [],
    "mains_sensors": [],
    "power_sensors": [],
    "legacy_writers": [],
    "room_sources": {},
}
