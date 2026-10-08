# Version 0.1.1

## Correction

A warm whole-house average could hold heating demand down indefinitely even when an individual room was persistently below its own target. The warm guard now has a bounded cold-room exception with native UI settings:

| Setting | Default |
| --- | --- |
| Entry deficit against the room's own target | 1.0 C |
| Exit deficit | 0.3 C |
| Continuous cold demand after actuator readiness | 20 minutes |
| Maximum rescue offset | 0, also limited by ready-zone ceiling |

Rescue ramps one offset step per configured interval (default ten minutes). It does not clear the warm latch, authorize electric space heating through it, bypass any fault or recovery hold, or change DHW/frequency behavior. Lost demand, invalid inputs and DHW reset its evidence. Restart and rescue-setting changes restart qualification. A new diagnostic binary sensor and Status attributes expose active/pending rescue rooms.

## Upgrade and Rollback

Back up the integration files, config entry and its own HA Store record before upgrading. Install through HACS and restart Home Assistant; no new manual helpers or source bindings are required. Existing targets, trim, ownership, warm latch, holds and cooldowns are preserved. New settings receive the documented defaults. Opening, idle and rescue timers conservatively restart.

The persistent storage schema is unchanged. To roll back, restore the previous runtime files and restart while retaining the **current** Store record, not an older backup that would erase newer holds. Review any retained pump offset before rollback: the previous warm guard can reduce it again, but no software rollback proves hydraulic safety. Never enable legacy and native writers together.

## Unchanged Limitations

No pump operating-mode, minimum/maximum-supply, DHW schedule/temperature, physical pump-speed, firmware, EV or alarm-reset change is included. Requested offset is not measured heat delivery. Physical flow and successful periodic hygiene heating remain unverified. Local thermal power/COP remain withheld while thermal metering is unverified.
