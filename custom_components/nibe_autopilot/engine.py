"""Pure, deterministic controller. No HA services, I/O, helpers or browser timers."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from .const import (
    CONDENSER_ALARMS,
    CRITICAL_ALARMS,
    DEFAULTS,
    OUTPUTS,
    REQUIRED_SOURCES,
    SETTINGS,
    SOURCES,
    STAGES,
)


def number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        result = float(value)
    except ValueError, TypeError:
        return None
    return result if math.isfinite(result) else None


def validate(config: dict) -> dict:
    """Server-side validation also applies to native entity changes."""
    config = DEFAULTS | config
    for key, setting in SETTINGS.items():
        value = number(config.get(key))
        if value is None or not setting.minimum <= value <= setting.maximum:
            raise ValueError(f"{key}: outside supported bounds")
        if (
            abs(
                (value - setting.minimum) / setting.step
                - round((value - setting.minimum) / setting.step)
            )
            > 1e-6
        ):
            raise ValueError(f"{key}: invalid step")
        config[key] = value
    for key in ("quiet_enabled", "ownership_reviewed"):
        if not isinstance(config[key], bool):
            raise ValueError(f"{key}: expected boolean")
    for key in ("night_start", "night_end"):
        parse_time(config[key])
    for keys in ([f"zone_offset_{n}" for n in range(6)], [f"zone_hz_{n}" for n in range(6)]):
        if [config[k] for k in keys] != sorted(config[k] for k in keys):
            raise ValueError("Zone ceilings must be nondecreasing")
    if config["brine_cold"] > config["brine_mild"] or config["reserve_a"] >= config["breaker_a"]:
        raise ValueError("Inconsistent thresholds")
    if config["room_rescue_exit"] >= config["room_rescue_enter"]:
        raise ValueError("Cold-room rescue exit must be below entry")
    for key in REQUIRED_SOURCES:
        if not config.get(key):
            raise ValueError(f"{key}: required")
    for key, (_, domain, _) in SOURCES.items():
        if config.get(key) and not valid_entity(config[key], domain):
            raise ValueError(f"{key}: invalid entity domain")
    if len(set(config[key] for key in OUTPUTS)) != 3:
        raise ValueError("Control outputs must be distinct")
    for key, domain in [
        ("climates", "climate"),
        ("indoor_sensors", "sensor"),
        ("mains_sensors", "sensor"),
        ("power_sensors", "sensor"),
        ("legacy_writers", "automation"),
    ]:
        values = config[key]
        if (
            not isinstance(values, list)
            or len(values) != len(set(values))
            or any(not valid_entity(value, domain) for value in values)
        ):
            raise ValueError(f"{key}: expected unique entity list")
    if not config["climates"] or not config["indoor_sensors"] or len(config["mains_sensors"]) != 3:
        raise ValueError(
            "Select thermostats, indoor sensors and exactly three mains-current phases"
        )
    if not isinstance(config["room_sources"], dict) or any(
        key not in config["climates"] or not valid_entity(value, "sensor")
        for key, value in config["room_sources"].items()
    ):
        raise ValueError("Invalid room temperature override")
    return config


def valid_entity(value: Any, domain: str) -> bool:
    import re

    return isinstance(value, str) and re.fullmatch(rf"{domain}\.[a-z0-9_]+", value) is not None


def parse_time(value: str) -> int:
    if not isinstance(value, str):
        raise ValueError("Invalid time")
    parts = value.split(":")
    if len(parts) not in (2, 3) or any(not p.isdigit() for p in parts):
        raise ValueError("Invalid time")
    hour, minute = map(int, parts[:2])
    second = int(parts[2]) if len(parts) == 3 else 0
    if hour > 23 or minute > 59 or second > 59:
        raise ValueError("Invalid time")
    return hour * 3600 + minute * 60 + second


@dataclass
class Reading:
    state: str = "unavailable"
    reported: float = 0
    attributes: dict = field(default_factory=dict)

    def fresh(self, now: float, age: float) -> bool:
        return self.state not in ("unavailable", "unknown", "") and 0 <= now - self.reported <= age

    def numeric(self) -> float | None:
        return number(self.state)

    def temperature(self) -> float | None:
        value = self.numeric()
        unit = self.attributes.get("unit_of_measurement")
        if value is None:
            return None
        if unit == "°F":
            return (value - 32) * 5 / 9
        return value if unit in ("°C", "C") else None

    def power(self) -> float | None:
        value = self.numeric()
        unit = self.attributes.get("unit_of_measurement")
        if value is None or value < 0:
            return None
        return value / 1000 if unit == "W" else value if unit == "kW" else None


@dataclass
class Memory:
    warm: bool = False
    recovery_until: float = 0
    global_until: float = 0
    condenser_until: float = 0
    last_offset: float = 0
    last_add: float = 0

    @classmethod
    def restore(cls, data: dict) -> Memory:
        if not isinstance(data, dict) or not isinstance(data.get("warm"), bool):
            raise ValueError("Invalid persisted controller state")
        for key in asdict(cls()):
            if key != "warm" and (number(data.get(key)) is None or float(data[key]) < 0):
                raise ValueError("Invalid persisted hold or cooldown")
        return cls(
            **{key: data[key] if key == "warm" else float(data[key]) for key in asdict(cls())}
        )


@dataclass
class Transient:
    zones_since: dict[str, float] = field(default_factory=dict)
    heater_idle_since: float | None = None
    cold_since: dict[str, float] = field(default_factory=dict)
    rescue_rooms: set[str] = field(default_factory=set)


@dataclass
class Decision:
    targets: dict[str, float]
    data: dict
    memory: Memory


def evaluate(
    config: dict,
    states: dict[str, Reading],
    memory: Memory,
    transient: Transient,
    now: float,
    local_second: int,
    climate_unit: str = "°C",
) -> Decision:
    """Reconcile current inputs, retaining physical delay and persistent fault semantics."""
    c = config
    m = Memory.restore(asdict(memory))

    def get(key):
        return states.get(c.get(key, ""), Reading())

    age = c["pump_max_age"]
    priority_reading = get("priority_entity")
    prio = priority_reading.state.upper().strip()
    prio = "HEATING" if prio == "HEAT" else prio
    priority_ok = priority_reading.fresh(now, age) and prio in ("OFF", "HEATING", "HOT WATER")
    dhw = priority_ok and prio == "HOT WATER"
    alarm = get("alarm_entity").numeric()
    hotgas = get("hot_gas_entity").temperature()
    if alarm in CRITICAL_ALARMS or (hotgas is not None and hotgas >= c["hot_gas_limit"]):
        m.global_until = max(m.global_until, now + c["fault_hold_seconds"])
    if alarm in CONDENSER_ALARMS:
        m.condenser_until = max(m.condenser_until, now + c["fault_hold_seconds"])
    global_hold = now < m.global_until
    condenser_hold = now < m.condenser_until
    indoor_readings = [states.get(e, Reading()) for e in c["indoor_sensors"]]
    indoor_ok = bool(indoor_readings) and all(
        e.fresh(now, age) and e.temperature() is not None for e in indoor_readings
    )
    indoor = (
        sum(e.temperature() for e in indoor_readings) / len(indoor_readings) if indoor_ok else None
    )
    sensors_ok = (
        indoor_ok
        and alarm is not None
        and alarm.is_integer()
        and hotgas is not None
        and all(get(key).fresh(now, age) for key in ("alarm_entity", "hot_gas_entity"))
    )
    if indoor is not None:
        if indoor >= c["comfort_target"] + c["warm_enter"]:
            m.warm = True
        elif m.warm and indoor <= c["comfort_target"] - c["warm_exit"]:
            m.warm = False
            m.recovery_until = now + c["recovery_seconds"]
    warm = m.warm or now < m.recovery_until
    errors, ready = [], []
    room_errors = {}
    zones_ok, all_off = bool(c["climates"]), bool(c["climates"])
    for entity_id in c["climates"]:
        zone = states.get(entity_id, Reading())
        all_off &= zone.state == "off"
        target = number(zone.attributes.get("temperature"))
        current = number(zone.attributes.get("current_temperature"))
        if climate_unit == "°F":
            target = (target - 32) * 5 / 9 if target is not None else None
            current = (current - 32) * 5 / 9 if current is not None else None
        override = c["room_sources"].get(entity_id)
        if override:
            r = states.get(override, Reading())
            current = r.temperature() if r.fresh(now, age) else None
        action = zone.attributes.get("hvac_action")
        valid = zone.state == "off" or (
            zone.state == "heat"
            and action in ("heating", "idle")
            and current is not None
            and target is not None
        )
        zones_ok &= valid
        if valid and zone.state == "heat":
            errors.append(target - current)
            room_errors[entity_id] = target - current
        if valid and zone.state == "heat" and action == "heating":
            since = transient.zones_since.setdefault(entity_id, now)
            if now - since >= c["zone_delay"]:
                ready.append(entity_id)
        else:
            transient.zones_since.pop(entity_id, None)
    transient.zones_since = {
        key: value for key, value in transient.zones_since.items() if key in c["climates"]
    }
    count = len(ready)
    error = 0.7 * max(errors) + 0.3 * sum(errors) / len(errors) if errors else 0
    zone_cap = c[f"zone_offset_{min(count, 5)}"]
    unsafe_space = global_hold or condenser_hold
    # A room-specific exception never clears the durable warm/fault/recovery holds.
    # Evidence restarts on DHW, faults, missing inputs or loss of ready demand.
    rescue_allowed = (
        m.warm
        and now >= m.recovery_until
        and not unsafe_space
        and sensors_ok
        and zones_ok
        and priority_ok
        and not dhw
    )
    candidates = set(ready) if rescue_allowed else set()
    for entity_id in set(transient.cold_since) | transient.rescue_rooms | candidates:
        deficit = room_errors.get(entity_id, 0)
        if entity_id not in candidates or deficit <= c["room_rescue_exit"] + 1e-6:
            transient.cold_since.pop(entity_id, None)
            transient.rescue_rooms.discard(entity_id)
        elif entity_id not in transient.rescue_rooms:
            if deficit >= c["room_rescue_enter"] - 1e-6:
                since = transient.cold_since.setdefault(entity_id, now)
                if now - since >= c["room_rescue_seconds"]:
                    transient.rescue_rooms.add(entity_id)
            else:
                transient.cold_since.pop(entity_id, None)
    rescue = bool(transient.rescue_rooms)
    protective = (
        unsafe_space or (warm and not rescue) or not sensors_ok or not zones_ok or not priority_ok
    )
    desired_offset = (
        -10
        if unsafe_space
        else -6
        if protective
        else min(max(round(error * c["kp"] + c["heat_bias"]), -6), zone_cap)
    )
    if rescue:
        desired_offset = min(desired_offset, c["room_rescue_offset"])
    offset = get("offset_entity").numeric()
    targets: dict[str, float] = {}
    if offset is not None and (not dhw or unsafe_space):
        if protective or offset > zone_cap or (rescue and offset > c["room_rescue_offset"]):
            targets["offset_entity"] = min(offset, desired_offset)
        elif now - m.last_offset >= c["offset_interval"]:
            step = 1 if rescue else 3 if error > 1.5 else 2 if error > 0.7 else 1
            targets["offset_entity"] = min(max(desired_offset, offset - step), offset + step)
    mains = [states.get(e, Reading()) for e in c["mains_sensors"]]
    mains_ok = len(mains) == 3 and all(
        r.fresh(now, c["mains_max_age"])
        and r.numeric() is not None
        and r.numeric() >= 0
        and r.attributes.get("unit_of_measurement") == "A"
        for r in mains
    )
    fuse = get("fuse_entity").numeric()
    allowance = 0.0
    if mains_ok and fuse is not None and fuse > 0:
        headroom = min(fuse, c["breaker_a"]) - c["reserve_a"] - max(r.numeric() for r in mains)
        allowance = max([kw for kw, amps in STAGES if amps <= headroom] or [0.0])
    outdoor = get("outdoor_entity").temperature() if get("outdoor_entity").fresh(now, age) else None
    if outdoor is None:
        outdoor = (
            get("outdoor_fallback_entity").temperature()
            if get("outdoor_fallback_entity").fresh(now, age)
            else None
        )
    brine = get("brine_entity").temperature() if get("brine_entity").fresh(now, age) else None
    request = 0.0
    if not global_hold and sensors_ok and priority_ok:
        if dhw:
            request = c["dhw_permission"]
        elif not condenser_hold and not warm and zones_ok and count > 2 and error > 0.5:
            base = (
                4
                if brine is not None and brine <= c["brine_cold"]
                else 2
                if brine is not None and brine <= c["brine_mild"]
                else 1.5
                if outdoor is not None and outdoor <= c["outdoor_cold"]
                else 0
            )
            request = base * (0.5 if count == 3 else 1)
    safe_add = math.floor(max(0, min(request, c["heater_cap"], allowance, 6)) * 2) / 2
    actual_heater = get("heater_power_entity")
    if (
        actual_heater.fresh(now, age)
        and actual_heater.power() is not None
        and actual_heater.power() < 0.1
    ):
        if transient.heater_idle_since is None:
            transient.heater_idle_since = now
    else:
        transient.heater_idle_since = None
    idle_stable = (
        transient.heater_idle_since is not None
        and now - transient.heater_idle_since >= c["heater_idle_seconds"]
    )
    current_add = get("heater_limit_entity").numeric()
    if current_add is not None:
        targets["heater_limit_entity"] = (
            safe_add
            if safe_add <= current_add or (idle_stable and now - m.last_add >= c["heater_interval"])
            else current_add
        )
    start, end = parse_time(c["night_start"]), parse_time(c["night_end"])
    night = (
        (start <= local_second < end)
        if start < end
        else (local_second >= start or local_second < end)
        if start > end
        else False
    )
    comfort_ok = indoor is not None and c["comfort_target"] - indoor < c["comfort_rescue"]
    # Unknown/stale priority releases the HA frequency cap, never guesses DHW from BT7.
    frequency = (
        120
        if dhw or not priority_ok or all_off
        else min(
            c[f"zone_hz_{min(count, 5)}"],
            c["quiet_hz"] if c["quiet_enabled"] and night and comfort_ok else 120,
        )
    )
    if get("frequency_limit_entity").numeric() is not None:
        targets["frequency_limit_entity"] = frequency
    powers = [states.get(e, Reading()).power() for e in c["power_sensors"]]
    power = sum(powers) if powers and all(p is not None for p in powers) else None
    reasons = [
        name
        for active, name in [
            (global_hold, "global_fault_hold"),
            (condenser_hold, "condenser_space_hold"),
            (warm, "warm_guard"),
            (rescue, "cold_room_rescue"),
            (not sensors_ok, "stale_or_missing_inputs"),
            (not priority_ok, "unknown_priority"),
            (not zones_ok, "unknown_zones"),
            (not mains_ok, "mains_unavailable"),
        ]
        if active
    ]
    return Decision(
        targets,
        {
            "priority": prio,
            "indoor": indoor,
            "demand_error": error,
            "ready_zones": count,
            "ready_entities": ready,
            "zones_ok": zones_ok,
            "sensors_ok": sensors_ok,
            "mains_fresh": mains_ok,
            "electrical_allowance": allowance,
            "circuit_power": power,
            "heater_idle_stable": idle_stable,
            "warm_guard": warm,
            "cold_room_rescue": rescue,
            "cold_room_rescue_entities": sorted(transient.rescue_rooms),
            "cold_room_pending_entities": sorted(
                set(transient.cold_since) - transient.rescue_rooms
            ),
            "global_hold": global_hold,
            "condenser_hold": condenser_hold,
            "requested_heater": safe_add,
            "target_offset": targets.get("offset_entity"),
            "target_heater": targets.get("heater_limit_entity"),
            "target_frequency": frequency,
            "alarm": alarm,
            "reasons": reasons,
        },
        m,
    )
