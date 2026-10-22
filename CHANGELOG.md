# Changelog

## 0.1.2 - 2026-10-22

- Read-only sustained frequency-limit overrun diagnostic with settling, freshness,
  unit and DHW-transition checks. It does not claim physical speed enforcement.
- Persistent observed DHW target-reaching records and a timestamp entity;
  incomplete cycles are discarded and hygiene success is never pump-confirmed.
- Optional observation source bindings with same-pump enabled-register discovery.
- Sustained mild room deficits qualify for existing bounded rescue after a longer
  delay. Offset ceilings, fault holds, heater limits and EV settings are unchanged.

## 0.1.0 - 2026-10-07

- Initial monitor-first Home Assistant integration for the F1255-6 3x400 V profile.
- Native preset setup and eleven options sections, room/source selectors and 35 numeric settings.
- Room demand, warm guard, actuator delays, quiet governor, separate DHW-aware fault holds and conservative electrical allowance.
- Persistent protection state, guarded takeover, single-writer reconciliation and bounded write confirmation.
- Native comfort controls, controller telemetry, redacted diagnostics and dashboard discovery attributes.
- Synthetic engine and Home Assistant framework tests; runtime-only installation ZIP.
- Monitor-first installation, explicit supervised takeover and documented rollback; public HACS custom-repository distribution.
