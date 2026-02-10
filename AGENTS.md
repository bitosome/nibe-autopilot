# NIBE F1255-6 R Autopilot (NibeGW + Home Assistant)

Last updated: February 10, 2026.

## 0) TL;DR

### Problem
NIBE F1255-6 R can overheat / trip on high pressure when floor loops close (slow Tiemme actuators, no direct indoor feedback on the heat pump side).

### Current architecture
- Transport: local RS-485 via `elupus/esphome-nibe` (NibeGW), no myUplink control path.
- Control writer: Home Assistant automations.
- Core control targets:
  - `number.heat_offset_s1_47011`
  - `number.max_int_add_power_47212`
- Electrical safety: 3-phase headroom clamp using Shelly 3EM + NIBE fuse setting.
- Night noise control: dedicated quiet automation caps compressor frequency.

### Non-goals / constraints
- Do not auto-change `select.operational_mode_47137` (keep Auto unless user changes).
- Do not introduce Temp Lux control.
- Do not use RMU/temperature injection path for floor-heating control.
- Keep one active writer for offset/add-heat logic.

## 1) Project Files

- `nibegw.yaml`
  - ESPHome firmware for NibeGW bridge (UDP mirror to HA).
- `NIBE autopilot.yaml`
  - Main control automation.
- `NIBE autopilot warm-room guard.yaml`
  - Overshoot guard with staged release.
- `NIBE night quiet mode.yaml`
  - Night compressor-noise limiter.
- `NIBE derived power and COP sensors.yaml`
  - Derived input/produced power and estimated COP sensors.
- `card.yml`
  - Current Lovelace dashboard (includes NIBE control + graphs).
- `nibe_entities_to_enable.txt`
  - Required entity enable list.

## 2) Live HA Inventory Snapshot (SSH)

As of February 10, 2026, Home Assistant reports:
- NIBE integration platform: `nibe_heatpump`
- Total NIBE entities: `988`
- Domain split:
  - `400 sensor`
  - `399 number`
  - `149 switch`
  - `20 binary_sensor`
  - `14 select`
  - `4 climate`
  - `1 water_heater`
  - `1 button`

Current project uses 34 NIBE entities directly in automations/cards.

## 3) Control Logic (Current)

## 3.1 Main automation: `NIBE autopilot`

### Triggers
- HA startup.
- Every 10 min (`offset` loop).
- Every 2 min (`dhw` / periodic helper).
- Alarm state change (`sensor.alarm_45001`, 30 s).

### Inputs
- Indoor demand:
  - `sensor.home_temperature_average`
  - `input_number.indoor_target_temperature`
- Room weighting (for tuned behavior):
  - multiple room sensors, weighted toward coldest room.
- Source/conditions:
  - `sensor.bt1_outdoor_temperature_40004`
  - `sensor.eb100_ep14_bt10_brine_in_temp_40015`
  - `sensor.eb100_ep14_bt11_brine_out_temp_40016`
  - DHW priority signal: `sensor.opt_boiler_has_priority_hot_water_41287`
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
  - primary: `sensor.opt_boiler_has_priority_hot_water_41287`
  - fallback heuristic with BT6/BT7/compressor Hz.
- Periodic HW assist:
  - if periodic zone active (BT7 high + DHW active), temporarily allows extra add-heat within headroom.
- Alarm path:
  - sets offset low, add-heat cap to 0, creates persistent notification.

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
  - ramp offset up toward max(pre-guard offset, `guard_exit_offset: 0`)
  - delay `guard_release_delay: 8 min`
  - retrigger main autopilot.

## 3.3 Night quiet mode: `NIBE night quiet mode`

### Logic
- Time window: 22:30 -> 06:30.
- If autopilot is on and comfort deficit < 0.7 C:
  - cap `number.max_comp_freq_47104` to 75 Hz.
- Otherwise restore to 120 Hz.
- Ensure `switch.hot_water_high_power_mode_48743` is off at night.

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
- `sensor.heat_meter_*_cpr_*` (compressor-only heat meters) currently 0.0 in this setup.
- `sensor.bf1_ep14_flow_40072` currently `unknown`.
- `sensor.aa23_be5_eme20_total_energy_42075` is unrealistic (very large rollover-like value), do not use for control.
- `sensor.compr_in_current_43147` appears scaled unexpectedly (not suitable as a primary control signal).
- `sensor.used_heating_power_average_24h_42101` reports with temperature unit metadata; not reliable for power analytics.

## 5) Dashboard (`card.yml`)

NIBE block includes:
- Controls:
  - autopilot enable
  - night quiet mode
  - HW high power mode
  - indoor target
  - max add-heat cap
  - heat bias
  - heat offset
  - max add heat
  - fuse setting
  - max compressor frequency
- Diagnostics:
  - alarm code/reset
  - compressor state/slow-down reason
  - DHW priority
  - supply/brine pump state + speeds
  - heat-medium and brine dT
- Power and efficiency visuals:
  - Curve & Power panel (offset/add/compressor input)
  - Input vs Produced Power (COP) panel
  - Produced Heat Totals panel

## 6) Additional NIBE Entities Useful For This House (Not Yet Actively Used)

These were checked live via SSH and are available/meaningful.

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
2. Load/update automations:
   - `NIBE autopilot.yaml`
   - `NIBE autopilot warm-room guard.yaml`
   - `NIBE night quiet mode.yaml`
3. Load/update sensors:
   - `NIBE derived power and COP sensors.yaml`
4. Reload Templates / restart HA if needed.
5. Apply dashboard from `card.yml`.
6. Confirm only one writer controls offset/add-heat.

## 8) Validation Checklist

- Offset loop runs every 10 min when not DHW-priority blocked.
- `number.max_int_add_power_47212` follows demand + headroom even when offset doesn’t change.
- During high room temp, guard engages and add-heat cap drops to 0.
- Night window caps compressor max frequency unless comfort deficit exceeds threshold.
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
