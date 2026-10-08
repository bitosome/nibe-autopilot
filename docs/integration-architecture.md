# Integration Architecture

## Boundaries

`NibeGW -> built-in nibe_heatpump entities -> NIBE Autopilot -> number.set_value`

The existing integration owns transport, polling and register entities. This backend owns supervision of only three outputs. Standard climate entities own room thermostat logic. The optional nibe-dashboard card only issues explicit comfort/room target requests.

## Files

| File | Responsibility |
| --- | --- |
| `const.py` | Validated model/electrical profile, setting catalog, defaults and legacy identities |
| `engine.py` | Pure decisions from normalized readings, UTC time, local quiet-window time and memory |
| `coordinator.py` | HA subscriptions, single writer, ownership/freshness gates, durable state and service confirmation |
| `config_flow.py` | Preset wizard and native menu-based options, with common server validation |
| `number.py`, `switch.py` | Native settings and explicit enable/quiet controls |
| `sensor.py`, `binary_sensor.py` | Decisions, measured circuit input, holds and controller health |
| `diagnostics.py` | Downloadable diagnostics without household entity IDs/labels |
| `strings.json`, `translations/en.json` | UI labels/help, generated from the catalog |

Memory persists the warm latch, recovery/global/condenser deadlines and offset/heater cooldown timestamps. Enable/error state is also persisted. No `initial` values wipe existing holds. First installation starts disabled. Evidence timers for actuator opening, cold-room rescue and actual heater idle restart after process/reload or binding changes. Ordinary tuning preserves actuator/idle timers; rescue setting changes clear only rescue evidence. Version 0.1.1 retains the version-1 storage schema and merges new bounded presets into older config entries without changing their existing settings.

## Important Semantics

- Indoor inputs require valid temperature units and fresh reports; all selected inputs must be available. Room thermostat attributes are converted from HA's configured temperature unit. Optional room sensor overrides use their own metadata/freshness.
- ESPHome can suppress unchanged states. Thermostat heat/idle demand and circuit power are checked for numeric availability rather than independent per-phase/zone liveness. An available but stale upstream thermostat can still mislead the controller; configure source availability properly. Delayed demand is never asserted as physical flow.
- Pump alarm/BT14, indoor average, priority and heater-idle evidence have bounded report age. Whole-house currents have their own shorter age. Use `last_reported`, not `last_changed`, for freshness.
- Negative or nonnumeric mains current is invalid. Maximum per-phase current and the worst intermediate heater-stage current are used conservatively; no balanced three-phase shortcut or subtraction of existing heater draw.
- Output validation checks entity registry integration/register identity, common pump instance, numeric availability, min/max/step and a fixed model envelope. Configurable source selectors are not permission to write arbitrary number entities.
- External ownership is checked per write, including after persistence awaits. A changed safety/priority decision during persistence cancels the proposed command. Network/service execution cannot be atomic with physical pump operation.
- A pending register value is not physical operation. Normal duplicates wait for acknowledgement. Protective decreases and DHW release can supersede pending values. Timeouts and exceptions latch control off. No automatic alarm reset is available.
- Warm-house rescue is a narrow offset exception, not a warm-latch reset. Each ready, actively heating room has its own continuous deficit timer (default 1 C for 1200 seconds after readiness) and 0.3 C exit hysteresis. Timers are not shared between rooms. Only known space-heating/OFF priority, valid inputs, no global/condenser/recovery hold and an existing warm latch permit qualification. DHW or loss of those conditions clears rescue evidence. Offset recovery remains bounded by demand, zone ceiling and a configurable nonpositive rescue ceiling, at one step per existing offset interval. Space-heating electric assistance stays blocked by the warm latch; frequency rules are unchanged. Status includes rescue reasons/room IDs, whereas downloadable diagnostics omit room IDs.
- No YAML or `.storage` files belonging to another integration are edited. The only storage file written is the component's own versioned HA Store record.

## Validation Scope

Pure-engine tests cover alarm lists, DHW exceptions, warm hysteresis, own-room targets, opening delays, phase-stage limits, timing, units, missing data and restart state. HA fixture tests cover native config flows, all options menus, actual entity platforms, setting services, monitoring/no-write behavior, ownership loss, storage and service failures, async decision changes and unload/reload. Pump I/O is mocked, not performed.

Before production activation, monitor-mode comparison and supervised handover remain necessary. No test here verifies physical valve travel, circulation, thermal meter validity, successful hygiene heating, mains CT placement or mechanical noise.
