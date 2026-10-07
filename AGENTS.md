# NIBE F1255-6 R Autopilot (NibeGW + Home Assistant)

Last updated: July 10, 2026.

## 0) TL;DR

### Problem
NIBE F1255-6 R can overheat / trip on high pressure when floor loops close (slow Tiemme actuators, no direct indoor feedback on the heat pump side).

### Current architecture
- Transport: local RS-485 via `elupus/esphome-nibe` (NibeGW), no myUplink control path.
- Underfloor heating zones: ESPHome `thermostat-controller.yaml` (8-channel relay board, `/config/esphome/`) drives per-room Tiemme loop actuators via 7 `climate.thermostat_controller_*` zones. `hvac_action == 'heating'` means that room's floor loop is open.
- Control writer: Home Assistant automations.
- Core control targets:
  - `number.heat_offset_s1_47011`
  - `number.max_int_add_power_47212`
  - `number.max_comp_freq_47104` (sole writer: `NIBE night quiet mode`)
- Zone-loop-aware overheat protection: autopilot + governor reduce offset / add-heat / compressor frequency when few floor loops are open (prevents high pressure into a shrinking loop area).
- Firmware overheat ceiling: `number.max_supply_system_1_47019` = 42 C (max flow-line temp) caps underfloor supply independent of all HA logic. See 3.5 for the full defense-in-depth stack.
- Electrical safety: 3-phase headroom clamp using Shelly 3EM + NIBE fuse setting.
- Night noise control: dedicated quiet automation caps compressor frequency.

### Non-goals / constraints
- Do not auto-change `select.operational_mode_47137` (keep Auto unless user changes).
- Do not introduce Temp Lux control.
- Do not use RMU/temperature injection path for floor-heating control.
- Keep one active writer per controlled entity: offset/add-heat = `NIBE autopilot` (+ warm-room guard); `max_comp_freq_47104` = `NIBE night quiet mode` only.
- Do not throttle the compressor during DHW priority (summer hot-water must run at full frequency).

## 1) Project Files

- `nibegw.yaml`
  - ESPHome firmware for NibeGW bridge (UDP mirror to HA).
- `thermostat-controller.yaml` (deployed on HA at `/config/esphome/`)
  - ESPHome firmware for the 8-channel relay board driving the 7 underfloor-heating zone actuators. Exposes `climate.thermostat_controller_*` entities.
- `NIBE autopilot.yaml`
  - Main control automation (offset + add-heat + zone-loop overheat guard).
- `NIBE autopilot warm-room guard.yaml`
  - Overshoot guard with staged release.
- `NIBE night quiet mode.yaml`
  - Compressor-frequency governor: night noise limiter + zone-loop compressor cap. Sole writer of `number.max_comp_freq_47104`.
- `NIBE derived power and COP sensors.yaml`
  - Derived input/produced power and estimated COP sensors.
- `card.yml`
  - Current Lovelace dashboard (includes NIBE control + graphs).
- `nibe_entities_to_enable.txt`
  - Required entity enable list.

## 2) Environment, Access & Topology

### Hardware / network topology
- Heat pump: NIBE F1255-6 R (6 kW ground-source, 3x400V). Reachable to HA only through the NibeGW bridge (no cloud/myUplink control path).
- NibeGW bridge: ESP32 running `nibegw.yaml` (`elupus/esphome-nibe`). RS-485 to the MODBUS 40 accessory (AA9) in the pump; mirrors the Modbus stream over UDP to HA at `192.168.0.13:9999` and accepts write/read requests. Acknowledges as `MODBUS40`.
- Home Assistant: HAOS at `192.168.0.13` (core `2026.7.1`). NIBE integration entry title `F1255 at 192.168.0.48`, domain `nibe_heatpump`, config entry id `01K6F6VHZG4BYFQY3CGY292A6Z`.
- Underfloor zone controller: ESP32 8-channel relay board running `thermostat-controller.yaml` (`/config/esphome/`). Relays drive per-room Tiemme loop actuators. Exposes 7 `climate.thermostat_controller_*` zones (see section 3.4 for the mapping).
- Electrical monitor: Shelly Pro 3EM providing `sensor.shelly_pro_3em_1_phase_a/b/c_current` for the add-heat headroom clamp.
- Room temperature comes from ESPHome light-switch sensors (`sensor.*_light_switch_temperature`) aggregated into per-room averages in `configuration.yaml`.

### SSH access & live introspection
- Shell: `ssh root@192.168.0.13` (HAOS host; `ha` CLI available; config under `/config`).
- Read a live entity state (SSH shell has `$SUPERVISOR_TOKEN`):
  - `curl -sS -H "Authorization: Bearer $SUPERVISOR_TOKEN" http://supervisor/core/api/states/<entity_id>`
- Render a Jinja template against live state (validate automation logic):
  - `curl -sS -H "Authorization: Bearer $SUPERVISOR_TOKEN" -H "Content-Type: application/json" -d '{"template":"..."}' http://supervisor/core/api/template`
- Call a service (e.g. set a number):
  - `POST http://supervisor/core/api/services/number/set_value` body `{"entity_id":"...","value":42}`
- Entity registry file (disabled flags, unique_ids): `/config/.storage/core.entity_registry` (read-only introspection; do not hand-edit while HA runs).

### Enabling a disabled NIBE entity (most are disabled by default)
- No UI available over SSH. Enable via the HA websocket API `config/entity_registry/update` with `disabled_by: null` (a pure-stdlib websocket client to `http://supervisor/core/websocket`, auth with `$SUPERVISOR_TOKEN`), then reload the entry:
  - `curl -X POST -H "Authorization: Bearer $SUPERVISOR_TOKEN" http://supervisor/core/api/config/config_entries/entry/01K6F6VHZG4BYFQY3CGY292A6Z/reload`
- This is how `max_supply_system_1_47019` and the overheat sensors were enabled (no full HA restart needed; reload returns `require_restart:false`).

### Where things live on HA vs this repo
- Automations run from `/config/automations.yaml` (NIBE blocks around lines 1531 / 1903 / 2159). The repo `NIBE *.yaml` files are the source of truth; deploy by pasting each into the matching block and reloading automations.
- Derived sensors are inlined in `/config/configuration.yaml` under `sensor:` (derivative + average) and `template:` (COP/power). The repo `NIBE derived power and COP sensors.yaml` mirrors them.
- ESPHome firmwares live in `/config/esphome/` (`nibegw.yaml`, `thermostat-controller.yaml`, plus light switches).
- Dashboard: `card.yml` is a single Lovelace `vertical-stack` pasted into the dashboard (needs the `apexcharts-card` custom card).

### Live inventory (as of 2026-07-10)
- `nibe_heatpump`: 988 entities total, 75 enabled.
- 7 ESPHome thermostat zone climates.
- Project uses ~40 NIBE entities directly in automations/cards.

### Helper entities (HA `input_*`, created via UI/storage)
- `input_boolean.nibe_autopilot_state` - master enable for all NIBE automations (currently `on`).
- `input_number.indoor_target_temperature` - comfort setpoint, 18-30 C step 0.5 (currently 22.5).
- `input_number.nibe_max_add_heat_kw` - user cap on internal electric add, 0-6 kW step 0.5 (currently 4.0).
- `input_number.nibe_heat_bias` - autopilot self-trim, -3..+3 step 0.5.
- `sensor.real_electricity_price_cheap_hours` - optional cheap-price signal (softer offset stepping when active).
- `sensor.home_temperature_average`, `sensor.outdoors_temperature_average` - average sensors defined in `configuration.yaml`.
  - RESOLVED (2026-07-10): `sensor.outdoors_temperature_average` was orphaned/`unavailable`. Autopilot + card now use `sensor.ecowitt_ws90_1_outdoor_temperature` (primary outdoor) with `sensor.bt1_outdoor_temperature_40004` fallback. The dead average is no longer referenced.

### Key NIBE control entities & live ranges
- `number.heat_offset_s1_47011` - heating curve offset. Entity range -10..+10 step 1. Autopilot works within span +/-6; warm-room guard and alarm path can go to -10. ~2.5 C supply per step.
- `number.max_int_add_power_47212` - internal electric addition (kW). Entity nominal 0-45 step 0.01, but real max for F1255-6 3x400V is 6.5 kW (factory 6). Always capped by `input_number.nibe_max_add_heat_kw` and phase headroom.
- `number.max_comp_freq_47104` - compressor max frequency (Hz). Raw int16 entity range; real operating envelope 17-120 Hz. Sole writer: `NIBE night quiet mode`.
- `number.min_comp_freq_47103` - compressor min frequency, 17 Hz.
- `number.fuse_47214` - property main fuse rating in the pump, 16 A (matches `main_breaker_a: 16`).
- `number.max_supply_system_1_47019` - max supply/flow-line temperature ceiling, 5-80 C, set to 42 C for underfloor (hardware overheat guard).
- `number.degree_minutes_32_bit_40940` / `number.degree_minutes_16_bit_43005` - degree minutes (heat demand accumulator).

## 3) Control Logic (Current)

## 3.1 Main automation: `NIBE autopilot`

### Triggers
- HA startup.
- Every 10 min (`offset` loop).
- Every 2 min (`dhw` / periodic helper).
- Alarm state change (`sensor.alarm_45001`, 30 s).
- Zone floor-loop change (`hvac_action` on the 7 `climate.thermostat_controller_*` zones, 60 s debounce).
- Hot-gas overheat (`hotgas`): `sensor.eb100_ep14_bt14_hot_gas_temp_40018` above 115 C for 30 s.

### Inputs
- Indoor demand:
  - `sensor.home_temperature_average`
  - `input_number.indoor_target_temperature`
- Room weighting (for tuned behavior):
  - per-zone room sensors (aligned to the 7 thermostat-controller zones), weighted toward coldest room: `sensor.workshop_light_switch_temperature`, `sensor.mira_s_room_light_switch_temperature`, `sensor.office_light_switch_1_temperature`, `sensor.wc_1_entrance_hallway_temperature_average`, `sensor.living_room_temperature_average`, `sensor.wc_2_light_switch_1_temperature`, `sensor.wc_2_shower_room_temperature_average`.
- Source/conditions:
  - `sensor.ecowitt_ws90_1_outdoor_temperature` (primary outdoor; falls back to `sensor.bt1_outdoor_temperature_40004`)
  - `sensor.eb100_ep14_bt10_brine_in_temp_40015`
  - `sensor.eb100_ep14_bt11_brine_out_temp_40016`
  - DHW / mode signal: `sensor.prio_43086` (`OFF` / `HOT WATER` / `HEATING`), fallback `sensor.opt_boiler_has_priority_hot_water_41287` + BT6/BT7/Hz heuristic.
  - Hot-gas overheat: `sensor.eb100_ep14_bt14_hot_gas_temp_40018`.
- Floor-loop demand (zone-loop overheat protection, see 3.4):
  - 7 `climate.thermostat_controller_*` zones (`hvac_action == 'heating'` = loop open).
- Electrical headroom:
  - `sensor.shelly_pro_3em_1_phase_a_current`
  - `sensor.shelly_pro_3em_1_phase_b_current`
  - `sensor.shelly_pro_3em_1_phase_c_current`
  - `number.fuse_47214`

### Controlled outputs
- `number.heat_offset_s1_47011`
- `number.max_int_add_power_47212`
- `input_number.nibe_heat_bias` (self-trim)

### Key behavior
- Offset controller:
  - proportional (`k_p = 1.5`), span clamp ±6.
  - dynamic step limit based on coldest-room error (`1/2/3` steps).
  - optional softer step if cheap-price status says active.
- Add-heat request:
  - outdoor and brine aware.
  - then clamped by `input_number.nibe_max_add_heat_kw`.
  - then clamped by 3-phase headroom:
    - `I_headroom = min(effective_breaker - safety_margin - IphaseA/B/C)`
    - `P_headroom = sqrt(3) * 400V * I_headroom`
    - stepped to 0.5 kW increments.
- DHW detection for skip logic:
  - primary: `sensor.prio_43086` (`'water' in state` = DHW active).
  - fallback: `sensor.opt_boiler_has_priority_hot_water_41287`, then BT6/BT7/compressor Hz heuristic.
- Periodic HW assist:
  - if periodic zone active (BT7 high + DHW active), temporarily allows extra add-heat within headroom.
- Alarm path:
  - sets offset low, add-heat cap to 0, creates persistent notification.
- Hot-gas overheat guard (`hotgas` trigger):
  - if `sensor.eb100_ep14_bt14_hot_gas_temp_40018` >= 115 C for 30 s: forces add-heat to 0, lowers offset by 3 steps, notifies. Pre-emptive net below the pump's own discharge trip (~135 C). Threshold tunable once running BT14 range is observed.

### Current safety constants
- `main_breaker_a: 16`
- `phase_safety_margin_a: 2`
- `nominal_line_voltage_v: 400`

## 3.2 Warm-room guard: `NIBE autopilot warm-room guard`

### Entry/exit
- Enter when indoor avg >= target + 0.4 C (for 2 min).
- Reduce offset in steps to guard floor:
  - `guard_min_offset: -6`
  - `guard_step: 2`
  - `guard_step_delay: 90 s`
- Force add-heat cap to 0 while guarding.
- Exit wait until indoor avg <= target - 0.3 C.
- Release:
  - ramp offset up toward `min( max(pre-guard offset, guard_exit_offset: 0), zone_offset_cap )` — release is clamped by open floor loops so it never pushes heat back into closed loops.
  - delay `guard_release_delay: 8 min`
  - retrigger main autopilot.

## 3.3 Night quiet mode / compressor governor: `NIBE night quiet mode`

### Logic
- Sole writer of `number.max_comp_freq_47104`.
- Triggers: 22:30, 06:30, every 10 min, and on any zone `hvac_action` change (30-60 s debounce).
- Noise target:
  - Time window 22:30 -> 06:30.
  - If autopilot is on and comfort deficit < 0.7 C: 75 Hz, else 120 Hz.
- Zone-loop cap (only when autopilot on, `active_zones > 0`, and not DHW priority — so summer DHW is never throttled):
  - open loops -> cap: `>=5`=120, `4`=100, `3`=85, `2`=65, `1`=55, `0`=50 Hz.
- Final `max_comp_freq` = `min(noise_target, zone_cap)`.
- Ensure `switch.hot_water_high_power_mode_48743` is off at night.

## 3.4 Zone-loop overheat protection (autopilot + governor)

### Rationale
When most floor loops close (rooms satisfied), pushing full supply temp / add-heat / compressor frequency into a shrinking loop area causes high pressure / overheat. The 7 `climate.thermostat_controller_*` zones report open loops via `hvac_action == 'heating'`.

### Zones (climate entity -> room -> relay(s) -> room temp sensor)
| Zone climate entity | Room | Relay(s) | Room temp sensor |
| --- | --- | --- | --- |
| `climate.thermostat_controller_workshop` | Workshop | 1 | `sensor.workshop_light_switch_temperature` |
| `climate.thermostat_controller_mira_s_room` | Mira's room | 2 | `sensor.mira_s_room_light_switch_temperature` |
| `climate.thermostat_controller_office` | Office | 3 | `sensor.office_light_switch_1_temperature` |
| `climate.thermostat_controller_wc_1_entrance_storeroom_hallway` | WC1 / entrance / storeroom / hallway | 4 | `sensor.wc_1_entrance_hallway_temperature_average` |
| `climate.thermostat_controller_kitchen_living_room` | Kitchen / living room | 5 + 7 | `sensor.living_room_temperature_average` |
| `climate.thermostat_controller_bedroom` | Bedroom | 6 | `sensor.wc_2_light_switch_1_temperature` |
| `climate.thermostat_controller_wc_2_shower_room` | WC2 / shower room | 8 | `sensor.wc_2_shower_room_temperature_average` |

- ESPHome thermostat params per zone: `heat_deadband/overrun 0.2 C`, `min_heating_run/off_time 10 min`, `min_idle_time 2 min`. `hvac_action`: `heating` = relay on = loop open; `idle` = satisfied/closed; `off` = zone disabled.
- These 7 room sensors are also the autopilot `room_sensors` list (coldest-room weighting).

### Definitions
- `open_zones` = count of zones with `hvac_action == 'heating'`.
- `active_zones` = count of zones not in `off` (participating this heating season).
- Self-regulating: a cold room opens its own loop (raising `open_zones`), which relaxes the caps.

### Caps by open loops (moderate profile)
- Offset upper cap: `>=5`=+6, `4`=+4, `3`=+2, `2`=0, `1`=-2, `0`=-4.
- Add-heat factor: `>=4`=1.0, `3`=0.5, `<=2`=0.0.
- Compressor cap: see 3.3.
- Fast guard (autopilot `zones` trigger): clamps offset down to the zone cap and forces add-heat to 0 when `open_zones <= 2`, gated off during DHW priority.

## 3.5 Overheat / high-pressure protection layers (defense in depth)

From outermost (firmware) to software, in order of robustness:
1. Hardware pressostat BP1 (refrigerant high-pressure) - physical safety switch, no Modbus register. Last-resort trip.
2. Max flow line temp (`number.max_supply_system_1_47019` = 42 C) - firmware ceiling on supply temp; the most robust automatic guard for the underfloor loops. Independent of all HA logic.
3. Max diff flow line temp (menu 5.1.3, maxdiff compressor 10 C / addition 3 C) - firmware sets degree minutes to 0 and stops the compressor when actual supply (BT2) exceeds calculated supply by the maxdiff; add-heat force-stopped sooner.
4. Zone-loop caps (this project): autopilot lowers offset + add-heat and the governor lowers `max_comp_freq` as open floor loops decrease, so demand is pulled back before the firmware guards ever trigger. Self-regulating (a cold room opens its own loop, relaxing caps).
5. Warm-room guard: staged offset pull-down on sustained whole-house overshoot, with zone-clamped release.
6. Hot-gas guard (this project, ACTIVE): `sensor.eb100_ep14_bt14_hot_gas_temp_40018` >= 115 C (30 s) forces add-heat to 0 and lowers offset 3 steps. Pre-emptive net below the pump's ~135 C discharge trip; tune the threshold after observing BT14 under load.
7. Observability: BT14 hot gas, `sensor.eb100_ep14_bt12_condensor_out_40017` (condenser-out), and the `calc_supply_s1` vs BT2 gap on the "Overheat watch" card.

## 4) Power, Heat, and COP Telemetry

## 4.1 Direct NIBE inputs (trusted)
- Electrical input power:
  - `sensor.compr_in_power_43141`
  - `sensor.int_el_add_power_43084`
- Produced heat energy totals:
  - `sensor.heat_meter_heat_cpr_and_add_total_system_42439`
  - `sensor.heat_meter_hw_cpr_and_add_total_system_42437`

## 4.2 Derived sensors (`NIBE derived power and COP sensors.yaml`)
- `sensor.nibe_total_input_power_kw`
  - compressor + internal additive power.
- `sensor.nibe_produced_space_heat_power_kw`
  - derivative of space heat energy total.
- `sensor.nibe_produced_dhw_heat_power_kw`
  - derivative of DHW heat energy total.
- `sensor.nibe_produced_heat_total_power_kw`
  - sum of produced space + DHW power.
- `sensor.nibe_estimated_cop_instant`
  - produced heat power / input power (guarded when input < 0.25 kW).

## 4.3 Known telemetry caveats
- `sensor.heat_meter_*_cpr_*` (compressor-only heat meters) currently 0.0 in this setup; use the `*_cpr_and_add_*` totals instead.
- `sensor.bm1_pressure_40857` (system water pressure) and `sensor.bf1_ep14_flow_40072` (flow) both read `unknown` on this install - no sensor data. Enabled but unusable; not on any chart/control.
- `sensor.aa23_be5_eme20_total_energy_42075` is unrealistic (very large rollover-like value), do not use for control.
- `sensor.compr_in_current_43147` appears scaled unexpectedly (not suitable as a primary control signal).
- `sensor.used_heating_power_average_24h_42101` reports with temperature unit metadata; not reliable for power analytics.

## 5) Dashboard (`card.yml`)

Lean single Lovelace `vertical-stack` (requires the `apexcharts-card` custom card). 6 cards:
1. `NIBE controls` (entities) - autopilot enable, night quiet, indoor target, add-heat cap, heat bias, max supply ceiling, offset, max add-heat, max comp freq.
2. `NIBE status` (glance) - compressor state, actual freq, operating priority (`prio_43086`), hot-gas BT14, COP, active alarm.
3. `Room Temperatures` - the 7 real per-zone sensors + target (15-25 C axis).
4. `Control & compressor` - offset column (left -10..10) + compressor actual Hz and `max_comp_freq` limit (right 0..130).
5. `Floor loops open (by room)` - stacked columns from each zone `hvac_action` (stack height = open loops 0-7).
6. `Overheat watch (condenser & supply)` - calc supply target, `max_supply_system_1_47019` ceiling (42 C dashed), supply BT2, condenser-out BT12, hot-gas BT14.

Deliberately dropped to keep it a daily-driver view (data still available in HA, just not charted): full 65-row entity dump, Pump Speeds, Heating Temperatures, Brine Temps, Brine dT, Input-vs-produced power & COP chart, Produced heat totals. Re-add any of these as a separate "Diagnostics" view if needed.

## 6) Additional NIBE Entities Useful For This House (Not Yet Actively Used)

These were checked live via SSH and are available/meaningful.

### Overheat / high-pressure observability (enabled + reloaded 2026-07-10)
- `sensor.eb100_ep14_bt14_hot_gas_temp_40018` — hot gas / compressor discharge temp. WORKS (~45 C idle). BEST refrigerant-overheat early-warning; rises fast before a high-pressure/high-temp trip. WIRED: drives the autopilot `hotgas` guard (>=115 C).
- `sensor.eb100_ep14_bt12_condensor_out_40017` — condenser-out (hot side) temp. WORKS (~48 C).
- `sensor.eb100_ep14_bt15_liquid_line_40019` (~34 C) + `sensor.eb100_ep14_bt17_suction_40022` (~38 C) — refrigerant circuit / superheat health. WORK.
- `sensor.calc_supply_s1_43009` — calculated target supply temp. WORKS (~24 C).
- `sensor.prio_43086` — operating priority (OFF / HOT WATER / HEATING / COOLING). WORKS. WIRED: now the primary DHW/mode signal in the autopilot + governor (fallback to `opt_boiler_has_priority_hot_water_41287` + BT6/BT7/Hz).
- `binary_sensor.freeze_protection_status_43013` (off), `sensor.inverter_limit_status_40316` (0), `sensor.inverter_fault_code_40324` (0) — WORK; diagnostics.
- `sensor.bm1_pressure_40857`, `sensor.bf1_ep14_flow_40072`, `binary_sensor.cpr_status_ep14_43435` — enabled but read `unknown/unavailable` (not broadcast by this pump). Do not use.
- Recommended follow-up: observe BT14 hot-gas range under compressor load, then add a hard guard that caps add-heat to 0 / lowers offset when BT14 exceeds a validated threshold. See 3.5.

### Priority A (high value for control/diagnostics)
- `switch.allow_additive_heating_47370`
  - hard block/allow additive heating by automation context.
- `switch.allow_heating_47371`
  - emergency heating permit state.
- `sensor.compressor_frequency_target_43182`
  - target vs actual compressor tracking.
- `sensor.compressor_frequency_request_40321`
  - request-level insight for limiter behavior.
- `sensor.compr_in_power_mean_43375`
  - smoothed power signal for quieter charts/COP trend.
- `sensor.inverter_alarm_code_40323`
  - early fault diagnosis.
- `sensor.compressor_starts_eb100_ep14_43416`
  - cycling intensity KPI.
- `sensor.tot_op_time_compr_eb100_ep14_43420`
  - compressor lifetime hours (trend/KPI).

### Priority B (tuning and night-noise refinement)
- `number.min_comp_freq_47103`
  - lower compressor bound.
- `number.speed_circ_pump_heat_47414`
  - manual heat pump speed setpoint reference.
- `number.speed_circ_pump_hw_47413`
  - manual DHW pump speed setpoint reference.
- `number.max_speed_circ_pump_heat_48458`
  - heat circuit max speed cap.
- `select.operational_mode_heat_medium_pump_47138`
  - currently AUTO, useful to display/watch.
- `select.operational_mode_brine_medium_pump_47139`
  - currently INTERMITTENT, useful to display/watch.

### Priority C (DHW hygiene/comfort observability)
- `select.hot_water_comfort_mode_47041`
- `switch.periodic_hw_47050`
- `number.periodic_hw_interval_47051`
- `number.stop_temperature_periodic_hw_47046`
- `switch.hw_production_47387`

### Priority D (usually avoid for control in this setup)
- `sensor.aa23_be5_eme20_total_energy_42075` (invalid scale for control logic)
- `sensor.bf1_ep14_flow_40072` (unknown)
- `sensor.heat_meter_heat_cpr_total_system_42447` and `sensor.heat_meter_hw_cpr_total_system_42445` (stuck 0)

## 7) Deployment / Update Order

1. Keep NibeGW transport active and verify entity availability.
2. Enable entities from `nibe_entities_to_enable.txt` (Settings -> Devices/Entities, or registry), then reload the NIBE config entry. Includes overheat sensors `bm1_pressure_40857` (currently unknown), `calc_supply_s1_43009`, `eb100_ep14_bt12_condensor_out_40017`, `bf1_ep14_flow_40072` (currently unknown), and `max_supply_system_1_47019` (enabled + set to 42 C for underfloor).
3. Load/update automations:
   - `NIBE autopilot.yaml`
   - `NIBE autopilot warm-room guard.yaml`
   - `NIBE night quiet mode.yaml`
4. Load/update sensors:
   - `NIBE derived power and COP sensors.yaml`
5. Reload Templates / restart HA if needed.
6. Apply dashboard from `card.yml`.
7. Confirm single writers: offset/add-heat = `NIBE autopilot` (+ warm-room guard); `max_comp_freq_47104` = `NIBE night quiet mode` only.

## 8) Validation Checklist

- Offset loop runs every 10 min when not DHW-priority blocked.
- `number.max_int_add_power_47212` follows demand + headroom even when offset doesn’t change.
- During high room temp, guard engages and add-heat cap drops to 0.
- Night window caps compressor max frequency unless comfort deficit exceeds threshold.
- Zone protection: with few floor loops open, offset/add-heat/compressor caps engage; caps relax as more loops open. DHW priority and all-zones-off (summer) disable the zone compressor cap.
- Produced power/COP sensors become stable after derivative warm-up window (~15 min).
- No breaker nuisance under EV charging (watch Shelly per-phase currents + add-heat cap).

## 9) Troubleshooting

### Add-heat cap seems stuck high/low
- Check:
  - `input_number.nibe_max_add_heat_kw`
  - Shelly per-phase currents
  - `number.fuse_47214`
  - autopilot state

### DHW causes odd controller pauses
- Inspect:
  - `sensor.opt_boiler_has_priority_hot_water_41287`
  - BT6/BT7 + compressor Hz fallback behavior

### COP spikes or zeros
- Expected around low load/defrost/transitions.
- COP is estimated from derivatives and input-power thresholds.

### Night noise still high
- Tune:
  - `quiet_max_comp_hz` in `NIBE night quiet mode.yaml`
  - night window times
  - `comfort_rescue_delta_c`

## 10) Safety Policy

- Keep `select.operational_mode_47137` untouched by automation.
- Keep Temp Lux out of automation/UI logic.
- Keep breaker safety margin in headroom clamp.
- Prefer clamping/offset shaping over hard mode switching.

## 11) Notes For Code Agents

- Preserve entity IDs exactly.
- Re-apply YAML idempotently.
- Do not silently remove safety clamps.
- If tuning duplicated constants, update all occurrences (startup/offset/DHW branches).
- Do not add RMU temperature injection controls unless explicitly requested.
- When recommending new entities, verify live state quality first (not only registry presence).

## 12) Doc-Validated Control Facts (F1255 Installer manual, `docs/`)

### Compressor frequency envelope
- Operating range ~17-120 Hz (menu 5.1.24 blockFreq: start 17-115, stop 22-120).
- Confirms zone compressor caps (50-120 Hz) and night cap (75) are all valid; `min_comp_freq_47103` bounds the low end.

### Internal electrical addition (menu 5.1.12)
- F1255-6 3x400V range: 0 - 6.5 kW (factory 6 kW). So `number.max_int_add_power_47212` max is 6.5 kW.
- `input_number.nibe_max_add_heat_kw` (default 4.0) must stay <= 6.5.
- Phase-current-vs-kW allocation table exists; heat pump auto-allocates add-heat to least-loaded phase when current sensors connected (matches the Shelly headroom clamp intent).

### Overheat / high-pressure — how the pump already protects itself
- Max flow line temp (menu 5.1.2): range 20-80 C, default 60 C. Underfloor recommended 35-45 C. Entity `number.max_supply_system_1_47019`.
  - DONE: enabled and set to 42 C (2026-07-10). Hard supply-temp ceiling for the underfloor loops — the most robust overheat guard, independent of offset shaping. Adjust only after confirming max floor temp with the floor supplier.
- Max diff flow line temp (menu 5.1.3): maxdiff compressor default 10 C, maxdiff addition default 3 C.
  - When actual supply (BT2) exceeds calculated supply by maxdiff, degree minutes are set to 0 and the compressor stops (heating-only demand); additive heat is force-stopped at maxdiff addition.
  - This is why the "Overheat watch" card compares `sensor.calc_supply_s1_43009` (target) vs `sensor.bt2_supply_temp_s1_40008` (actual): a closing gap toward +10 C means the pump is about to cut out.

### Pressure signal clarification
- `sensor.bm1_pressure_40857` (BM1) is heating-system WATER pressure (fill/expansion, ~0.5-2.5 bar) — use for water-side health (low = air/leak), NOT the refrigerant trip. NOTE: on this install BM1 currently reads `unknown` (no sensor data), same as `sensor.bf1_ep14_flow_40072` — do not rely on either yet.
- The actual high-pressure trip is refrigerant pressostat BP1 (hardware safety switch, no Modbus register). Best software proxy for refrigerant overheat is `sensor.eb100_ep14_bt12_condensor_out_40017` (condenser-out temp, live ~50 C) plus the BT2-vs-calc-supply gap above.
- Caveat: calc-supply-vs-BT2 only compares meaningfully during space heating. During DHW, BT2/condenser run hot (~50 C) while `calc_supply_s1` stays at the low space-heat target, so a large gap during DHW is normal, not an overheat.

### Curve offset scaling
- Offset of +2 steps raises supply temp ~5 C at all outdoor temps (~2.5 C per step). Confirms span +/-6 is a meaningful control range for this system.
