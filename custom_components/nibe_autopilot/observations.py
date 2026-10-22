"""Read-only observations. Never assert pump-confirmed hygiene or alter targets."""

from dataclasses import dataclass, field

from .engine import Reading


@dataclass
class Observations:
    last: dict = field(default_factory=dict)
    last_target: dict = field(default_factory=dict)
    previous: str | None = None
    tick: float | None = None
    stable_key: tuple | None = None
    stable_since: float = 0
    excess_since: float | None = None
    cycle: dict | None = None

    def update(self, readings, now, age, active):
        def get(key):
            return readings.get(key, Reading())

        def numeric(key, unit):
            r = get(key)
            value = r.numeric() if r.fresh(now, age) else None
            return value if r.attributes.get("unit_of_measurement") == unit else None

        priority = get("priority")
        prio = priority.state.upper() if priority.fresh(now, age) else None
        if prio == "HEATING":
            prio = "HEAT"
        if prio not in ("HEAT", "HOT WATER", "OFF"):
            prio = None
        gap = self.tick is not None and not 0 <= now - self.tick <= age
        self.tick = now
        if gap:
            self.previous = None
            self.cycle = None
            self.stable_key = None
            self.excess_since = None
        actual = numeric("actual", "Hz")
        cap = numeric("cap", "Hz")
        valid = (
            active
            and prio == "HEAT"
            and actual is not None
            and actual >= 0
            and cap is not None
            and 17 <= cap <= 120
        )
        key = (prio, cap) if valid else None
        if key != self.stable_key or not valid:
            self.stable_key = key
            self.stable_since = now
            self.excess_since = None
        mismatch = None
        if valid:
            mismatch = False
            if now - self.stable_since >= 600 and actual > cap + 3:
                if self.excess_since is None:
                    self.excess_since = now
                mismatch = now - self.excess_since >= 300
            else:
                self.excess_since = None

        temp = get("temperature")
        stop = get("stop")
        bt6 = temp.temperature() if temp.fresh(now, age) else None
        target = stop.temperature() if stop.fresh(now, age) else None
        enabled = get("periodic")
        alarm = get("alarm")
        alarm_value = alarm.numeric() if alarm.fresh(now, age) else None
        valid_cycle = (
            prio is not None
            and bt6 is not None
            and target is not None
            and 30 <= target <= 80
            and enabled.fresh(now, age)
            and enabled.state == "on"
            and alarm_value is not None
        )
        if not valid_cycle:
            self.cycle = None
            self.previous = None
        else:
            if prio == "HOT WATER" and self.previous in ("HEAT", "OFF") and bt6 < target:
                self.cycle = {"started": now, "target": target, "peak_bt6": bt6, "failed": False}
            if self.cycle:
                if self.cycle["target"] != target:
                    self.cycle = None
                else:
                    if prio == "HOT WATER":
                        self.cycle["peak_bt6"] = max(self.cycle["peak_bt6"], bt6)
                    self.cycle["failed"] |= alarm_value == 181
                    # Only temperatures observed DURING DHW qualify, not post-stop warming.
                    if prio != "HOT WATER":
                        # Do not let a post-stop sample establish target attainment.
                        result = (
                            "failed_alarm_181"
                            if self.cycle["failed"]
                            else "target_reached_inferred"
                            if self.cycle.get("reached")
                            else "target_not_observed"
                        )
                        self.last = self.cycle | {"ended": now, "result": result}
                        if result == "target_reached_inferred":
                            self.last_target = dict(self.last)
                        self.cycle = None
                    else:
                        self.cycle["reached"] = bool(self.cycle.get("reached") or bt6 >= target)
            self.previous = prio
        return {
            "frequency_limit_exceeded": mismatch,
            "frequency_observation": "unavailable"
            if mismatch is None
            else "exceeded"
            if mismatch
            else "not_detected",
            "dhw_observation": "failed_alarm_181"
            if alarm_value == 181
            else "observing"
            if self.cycle
            else self.last.get("result", "not_observed"),
            "last_dhw_observation": dict(self.last),
            "last_target_reached_observation": dict(self.last_target),
        }
