# Migration and Rollback

## Before Installation

1. Back up HA configuration, automations, helper state, dashboard configuration and the current three pump register values. Preserve any active global/condenser/recovery holds.
2. Keep NIBE Auto mode, existing NibeGW/NIBE Heat Pump integration and thermostat firmware. Do not change periodic boost or safety settings as part of this migration.
3. Install the custom component with explicit authorization and restart HA. Add NIBE Autopilot through Devices & services. It starts monitor-only; keep all existing controllers running during observation.
4. Review every source mapping. Whole-house current inputs must include both EV charging and heat pump. Circuit power inputs must cover only the heat pump, with no total/phase double counting. Thermostats keep individual targets.
5. Compare proposed targets, reasons and holds against the YAML controller over heating and DHW operation. A proposed target is not sent in monitor mode. Note deliberate stricter outdoor/brine/priority freshness checks. This release has automated test coverage, not completed live thermal commissioning.

## Controlled Handover

1. Choose a supervised interval when no hygiene cycle is in progress. Resolve physical faults rather than treating software migration as a repair.
2. In Configure > Controller ownership and migration, select every legacy writer and acknowledge the ownership review. Known original automation IDs/names and literal number writers are also detected, but templated/external writers cannot be comprehensively discovered.
3. Disable **all three** legacy controllers: main autopilot, warm-room guard and night/compressor governor. Turning off only the old master helper is insufficient while writer automations remain enabled. The integration never disables them for you.
4. Keep the legacy helpers intact. The integration imports the warm latch, global hold, condenser hold, recovery time and both last-write timestamps, merging by maximum. If some helpers exist but others are missing/unavailable, activation is blocked. Restore them rather than clearing active holds.
5. Verify NIBE is still Auto, all required inputs are available, output registry bindings are correct, and integration status has no blocking error. Then explicitly turn on **Control enabled**.
6. Confirm one writer, register acknowledgements and expected heating/DHW behavior. Monitor actual power and alarms, not just permission. Confirm hygiene completion on the pump; the integration cannot certify it.
7. Switch the dashboard to the integration status sensor. Old input-number/master helpers no longer configure the new backend; do not retain ambiguous duplicate comfort controls.

No extra UI helpers or YAML package are required by the new backend. Keep the old package and automations disabled, not deleted, until supervised validation and rollback testing are complete. Retain unrelated templates and sensors used elsewhere.

## Stop and Roll Back

1. Explicitly turn off Control enabled **before** restoring another controller. This attempts one frequency release to 120 Hz only when safe ownership/Auto checks pass. It does not reset the offset or heater limit.
2. Record the integration's current warm guard, global/condenser hold-until timestamps and cooldowns. The old helpers were not kept synchronized during integration control. Never re-enable old controllers with expired helper timestamps while the new integration still has active protection holds. Under explicit authorization, merge the newer timestamps/latch back into legacy helpers or wait for physically verified clearance and hold expiry.
3. Verify the integration is off/unloaded, then re-enable the three known-good YAML controllers together and verify their master state and writes. Do not operate both at once.
4. If returning to NIBE-only operation instead, review the retained three register settings on the pump and deliberately restore an agreed baseline. Removing an integration is not an automatic return to factory settings.
5. Keep the integration storage record in backups. Corrupt/missing protection state must not be bypassed merely to resume heating. Investigate the failure before a manual reset or reinstallation.

## Distribution

The owner made the repository public on October 7, 2026. It can be added as a HACS custom repository (Integration). A runtime-only manual-install ZIP is also available. Historical household configuration remains in Git history; do not add live registry exports, credentials, raw logs or private deployment backups to the public repository.
