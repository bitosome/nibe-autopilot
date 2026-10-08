# NIBE Autopilot

A local Home Assistant custom integration for room-aware supervision of a **NIBE F1255-6, 3x400 V, in Auto mode**. It moves the controller out of YAML automations into a testable backend with native setup, options, comfort controls and diagnostics.

It uses your existing **NIBE Heat Pump integration and NibeGW bridge**. It does not replace their transport or create a second Modbus connection. Not an official NIBE product or a general controller for every NIBE model.

**First installation is monitor-only. It does not take control, disable automations, enable registers, change pump settings or create manual helpers.** Read [migration and rollback](docs/integration-migration.md) before enabling it. Hardware commissioning and a successful periodic hygiene cycle cannot be established by this software.

## Installation

Requires Home Assistant **2026.9.4 or newer**. Tested against 2026.9.4 / Python 3.14; later versions still require regression testing.

The repository is public and supports installation as a HACS custom repository. This is not a listing in the default HACS catalog. Do not publish live configuration, credentials, registry exports or raw household logs in issues or pull requests.

For manual installation, the build artifact contains only `custom_components/nibe_autopilot/`. Install that directory under the HA configuration directory, restart HA, then choose **Settings > Devices & services > Add integration > NIBE Autopilot**. Installing files/restarting a live system still requires the owner's approval.

Add `https://github.com/bitosome/nibe-autopilot` in **HACS > Custom repositories**, category **Integration**, download it and restart HA. The `hacs.json` and standard integration directory layout are provided. HACS listing/submission is separate from a custom-repository installation.

## Native Configuration

Setup suggests existing familiar entities when they exist, and imports the three everyday helper values as suggestions. Review the selections. Everything else has the current controller's conservative presets. Source integrations can be ESPHome, Shelly, template sensors, MQTT or any other source exposing suitable HA entities and units.

| Configure section | Purpose |
| --- | --- |
| NIBE pump entities | Three controlled numbers plus read-only mode, priority, alarm, BT14, heater power and fuse |
| Rooms and indoor temperature | Heat/off climate entities; one average sensor or several indoor sensors |
| Room temperature overrides | Optional current-temperature sensor per thermostat; its target remains its own |
| Electrical and source sensors | Three whole-house current phases, optional circuit power, outdoor/fallback and brine |
| Everyday comfort | House reference temperature, user heater allowance and manual trim |
| Heating response and warm guard | Gain, hysteresis, opening/recovery delays, ramp interval and bounded cold-room rescue |
| Ready-zone ceilings | Separate offset and frequency ceilings for zero through five-or-more ready zones |
| Night quiet mode | Enable, start/end, frequency cap and comfort override |
| Electric heater limits | Breaker bound, reserve, DHW permission and increase delays |
| Protection and freshness | Fault duration, hot-gas threshold and input report ages |
| Controller ownership and migration | Legacy writer selection and explicit ownership review |

Every numeric setting is also a native `number` entity. Everyday settings appear as controls; advanced tuning is categorized as configuration. All changes receive server-side bounds/cross-field validation. Changing ordinary tuning does not restart actuator timers. Changing cold-room rescue settings restarts only its qualification evidence. Source/ownership changes require control off and disarm it until explicitly enabled again.

Hard limits are deliberately not arbitrary UI fields: the validated profile does not allow increasing the main-breaker bound beyond 16 A, reducing the 2 A reserve, increasing DHW permission beyond 3 kW, raising BT14 above 115 C, removing critical fault guards or writing unrelated pump registers. Another electrical/model profile needs separate engineering validation.

## Preserved Control Rules

- One writer of offset **47011**, heater permission **47212** and compressor cap **47104**. Output registry entries must belong to the same NIBE Heat Pump integration instance and the expected registers.
- Room demand uses **70% worst deficit + 30% mean deficit**, each against that thermostat's own target. ESPHome `heat/off` and `hvac_action: heating/idle` are supported.
- Default opening allowance is eight minutes. Closing/unavailable demand drops immediately; restart resets these unverified opening timers. Relay demand is **not measured valve position or flow**.
- Warm entry is reference +0.4 C, exit reference -0.3 C, with eight minutes of recovery. Manual trim remains manual, with no windup-prone integrator or electricity-price modulation.
- A warm house average must not indefinitely mask a cold room. While the warm latch remains on, an actively heating, ready room at least **1 C below its own target for another 20 minutes** qualifies for limited rescue. The offset recovers at **one step per ramp interval**, capped at **zero or the stricter ready-zone ceiling**. Rescue exits at a 0.3 C deficit, lost ready demand, DHW, a fault/recovery hold or invalid inputs. It does **not** clear the warm latch, permit electric space heat through that latch or lift frequency limits. All four rescue settings are available under Configure; its exit must be below entry. Restart resets rescue evidence. These defaults are conservative software settings, not a claim of physically commissioned comfort or flow.
- Offset changes ramp no faster than ten minutes; protective decreases are immediate on reconciliation. Minimum supply may still prevent offset changes from stopping heating.
- Quiet hours default to 22:30-06:30, 75 Hz, with a 0.7 C comfort rescue. **Fresh confirmed DHW always releases the HA cap to 120 Hz.** Unknown/stale priority also releases frequency rather than guessing from cylinder temperature. Firmware exclusions still apply.
- Global critical alarms/hot-gas faults suppress addition including DHW. **Condenser 162/163 holds suppress space heating only**, not otherwise-permitted fresh DHW assistance. Holds last at least ten minutes and extend while a fault remains.
- Alarm **181** is reported but never reset and never used to block otherwise-permitted DHW assistance. No alarm-clear or hot BT7 reading is labelled a successful hygiene cycle.
- Electrical permission uses three fresh **whole-house** phase currents, the fuse bound and conservative worst-phase intermediate heater stages. EV charging is already part of those readings. Existing heater current is not subtracted. Increases require five minutes of confirmed heater idle and ten minutes since the last cap change; decreases do not wait.
- Stale/unavailable critical readings withhold added heat and extra space-heating demand. Celsius/Fahrenheit temperatures and W/kW circuit power are normalized. Static fuse settings are not treated as rapidly changing telemetry.

No operating-mode changes, room-temperature injection, forced boost, DHW temperature/schedule/high-power changes, pump-speed control, alarm resets or degree-minute resets are implemented.

## Dashboard

Use [NIBE Dashboard](https://github.com/bitosome/nibe-dashboard), version 0.2.0 or newer, or ordinary HA cards. Select the integration's **Status** sensor in the card's visual editor:

```yaml
type: custom:nibe-dashboard
controller_entity: sensor.nibe_autopilot_status
```

Use the actual entity ID if HA renames it. The status sensor advertises the integration's comfort entities and configured rooms; no separate list of room helpers is needed. The frontend remains optional and does not run control logic. It must never write raw pump controls. Legacy YAML-helper mode remains available separately.

Telemetry includes circuit electrical input, electrical allowance, delayed ready-zone count, room demand, current holds and proposed control targets. A separate Cold-room rescue binary sensor distinguishes the bounded exception from the still-latched warm guard; Status attributes identify qualifying and pending rooms. **Requested targets, acknowledged register values and physical results are different things.** Produced heat/COP remain withheld because the local heat meters/flow readings have not been verified.

## Reliability and Limitations

State changes trigger reconciliation, with a one-minute periodic fallback. One async lock serializes decisions and writes. Inputs are rechecked after storage I/O before sending a command. Warm latch, fault/recovery holds and write cooldowns survive restart in HA storage; actuator and heater-idle evidence intentionally does not.

Storage errors, service exceptions, confirmation timeouts and detected competing writers stop control. Automatic discovery of other writers is necessarily incomplete: scripts with templates, external programs and pump-side settings still require an ownership review. Auto mode must be fresh and confirmed. A temporary non-Auto/missing-mode condition blocks commands; if still enabled, it can resume when Auto is confirmed. A detected competing writer instead latches control off.

Explicitly turning off control releases only the HA frequency cap to 120 Hz once, when ownership and mode checks allow. It leaves offset/heater cap unchanged. Unloading, shutdown, failure or removal performs **no cleanup pump writes**. The last successful pump settings can remain in force if HA stops. Follow the documented rollback; this is not a hardware watchdog or breaker/flow protection.

There is no automatic retry storm: an unconfirmed write has a five-minute deadline. A more protective heater/offset decrease or DHW frequency release may supersede a pending command. HA/NibeGW communications and register polling remain asynchronous. Physical load monitoring, hydraulic flow, floor-temperature protection and noise diagnosis remain separate work.

## Development

```sh
python3.14 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/python -m pytest integration_tests
.venv/bin/ruff check custom_components/nibe_autopilot integration_tests scripts/generate_integration_strings.py scripts/build_integration.py
PYTHONPATH=. .venv/bin/python scripts/generate_integration_strings.py
.venv/bin/python scripts/build_integration.py
```

Tests use synthetic HA states and mocked pump services, never production equipment. The release ZIP contains only runtime integration files. Existing YAML, audit documents and historical tests remain in this repository as migration references, not as an additional controller to run alongside the integration. See [architecture](docs/integration-architecture.md).
