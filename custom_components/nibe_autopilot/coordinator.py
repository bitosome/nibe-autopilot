"""Single-writer HA adapter with persistent holds and explicit takeover gates."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from datetime import timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import DOMAIN, LEGACY_HOLDS, LEGACY_IDS, LEGACY_WRITERS, OUTPUTS, SOURCES
from .engine import Memory, Reading, Transient, evaluate, number, validate

LOGGER = logging.getLogger(__name__)


class AutopilotCoordinator(DataUpdateCoordinator):
    """Observe existing HA entities; never create a second Modbus connection."""

    def __init__(self, hass: HomeAssistant, entry):
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=60),
            request_refresh_debouncer=Debouncer(hass, LOGGER, cooldown=1, immediate=True),
        )
        self.entry = entry
        self.config = validate(dict(entry.data) | dict(entry.options))
        self.memory = Memory()
        self.transient = Transient()
        self.enabled = False
        self.error = ""
        self.storage_error = False
        self.closing = False
        self.started = False
        self.lock = asyncio.Lock()
        self.store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self.pending: dict[str, tuple[float, float]] = {}
        self._saved = None
        self._unsub = None

    def snapshot(self) -> dict[str, Reading]:
        return {
            state.entity_id: Reading(
                state.state, state.last_reported.timestamp(), dict(state.attributes)
            )
            for state in self.hass.states.async_all()
        }

    async def async_initialize(self):
        try:
            stored = await self.store.async_load()
            if stored is not None:
                self.memory = Memory.restore(stored["memory"])
                if not isinstance(stored.get("enabled"), bool):
                    raise ValueError("Invalid enabled state")
                self.enabled = stored["enabled"]
                self.error = str(stored.get("error", ""))
            else:
                now = dt_util.utcnow().timestamp()
                self.memory.last_offset = self.memory.last_add = now
        except Exception:
            LOGGER.exception("Controller state cannot be restored; all writes disabled")
            self.enabled = False
            self.storage_error = True
            self.error = "persistent_state_unavailable"
        await self.async_config_entry_first_refresh()

    @callback
    def async_start(self):
        """Subscribe only after platforms have loaded; unsubscribed on unload."""
        self.started = True
        self._listen()
        self.hass.async_create_task(self.async_request_refresh())

    @callback
    def _listen(self):
        if self._unsub:
            self._unsub()
        ids = {self.config[key] for key in SOURCES if self.config.get(key)}
        for key in (
            "climates",
            "indoor_sensors",
            "mains_sensors",
            "power_sensors",
            "legacy_writers",
        ):
            ids.update(self.config[key])
        ids.update(self.config["room_sources"].values())
        ids.update(LEGACY_WRITERS)
        ids.update(LEGACY_HOLDS.values())
        ids.add("input_boolean.nibe_warm_room_guard")
        ids.update(s.entity_id for s in self.hass.states.async_all("automation"))
        self._unsub = async_track_state_change_event(self.hass, list(ids), self._event)

    @callback
    def _event(self, _event):
        if not self.closing:
            self.hass.async_create_task(self.async_request_refresh())

    def legacy_entities(self) -> set[str]:
        ids = set(self.config["legacy_writers"])
        registry = er.async_get(self.hass)
        ids.update(
            entity.entity_id
            for entity in registry.entities.values()
            if entity.domain == "automation"
            and (entity.entity_id in LEGACY_WRITERS or str(entity.unique_id) in LEGACY_IDS)
        )
        for s in self.hass.states.async_all("automation"):
            if s.entity_id in LEGACY_WRITERS or str(s.attributes.get("id")) in LEGACY_IDS:
                ids.add(s.entity_id)
        # Known literal number writers are also detected, even after renaming.
        component = self.hass.data.get("automation")
        for entity in getattr(component, "entities", []):
            raw = json.dumps(getattr(entity, "raw_config", None), default=str)
            if "number.set_value" in raw and any(self.config[key] in raw for key in OUTPUTS):
                ids.add(entity.entity_id)
        return ids

    def ownership_error(self) -> str | None:
        if not self.config["ownership_reviewed"]:
            return "ownership_not_reviewed"
        for entity_id in self.legacy_entities():
            s = self.hass.states.get(entity_id)
            if s is None or s.state != "off":
                return "legacy_writer_active_or_unavailable"
        registry = er.async_get(self.hass)
        entries = []
        for key, register in zip(OUTPUTS, ("47011", "47212", "47104"), strict=True):
            entity = registry.async_get(self.config[key])
            if (
                entity is None
                or entity.platform != "nibe_heatpump"
                or not str(entity.unique_id).endswith(register)
            ):
                return "unverified_nibe_outputs"
            entries.append(entity.config_entry_id)
        if len(set(entries)) != 1 or entries[0] is None:
            return "outputs_belong_to_different_pumps"
        return None

    def operating_error(self) -> str | None:
        if not self.hass.is_running:
            return "home_assistant_starting_or_stopping"
        state = self.hass.states.get(self.config["mode_entity"])
        if state is None or state.state.strip().upper() != "AUTO":
            return "pump_not_confirmed_auto"
        if (
            not 0
            <= dt_util.utcnow().timestamp() - state.last_reported.timestamp()
            <= self.config["pump_max_age"]
        ):
            return "operating_mode_stale"
        return None

    def import_legacy(self) -> bool:
        """Merge (never shorten) existing holds, including immediately before takeover."""
        warm = self.hass.states.get("input_boolean.nibe_warm_room_guard")
        states = {key: self.hass.states.get(entity_id) for key, entity_id in LEGACY_HOLDS.items()}
        if warm is None and all(s is None for s in states.values()):
            return True
        if (
            warm is None
            or warm.state not in ("on", "off")
            or any(
                s is None
                or s.state in ("unknown", "unavailable")
                or number(s.attributes.get("timestamp")) is None
                for s in states.values()
            )
        ):
            return False
        self.memory.warm |= warm.state == "on"
        for key, s in states.items():
            setattr(
                self.memory, key, max(getattr(self.memory, key), float(s.attributes["timestamp"]))
            )
        return True

    async def persist(self):
        if self.storage_error:
            raise HomeAssistantError(
                "Persistent state unavailable; restore the controller storage before enabling control"
            )
        value = {"memory": asdict(self.memory), "enabled": self.enabled, "error": self.error}
        if value == self._saved:
            return
        try:
            await self.store.async_save(value)
        except Exception as exc:
            self.storage_error = True
            self.enabled = False
            self.error = "persistent_state_write_failed"
            raise HomeAssistantError(
                "Controller storage write failed; pump writes stopped"
            ) from exc
        self._saved = value

    def _evaluate(self, memory=None):
        now = dt_util.utcnow()
        local = dt_util.as_local(now)
        decision = evaluate(
            self.config,
            self.snapshot(),
            self.memory if memory is None else memory,
            self.transient,
            now.timestamp(),
            local.hour * 3600 + local.minute * 60 + local.second,
            self.hass.config.units.temperature_unit,
        )
        self.memory = decision.memory
        return decision

    async def async_set_enabled(self, enabled: bool):
        async with self.lock:
            if self.closing:
                raise HomeAssistantError("Controller is unloading")
            if enabled:
                error = self.ownership_error() or self.operating_error()
                if error:
                    raise HomeAssistantError(error)
                if not self.import_legacy():
                    raise HomeAssistantError(
                        "Legacy hold helpers are incomplete; restore them before takeover"
                    )
                if self.storage_error:
                    raise HomeAssistantError("Persistent state cannot be restored")
                self.enabled = True
                self.error = ""
                await self.persist()
            else:
                was_enabled = self.enabled
                self.enabled = False
                await self.persist()
                # Match the legacy master-off transition; do not reset offset or heater cap.
                if was_enabled and not self.ownership_error() and not self.operating_error():
                    try:
                        await self._write("frequency_limit_entity", 120, release=True)
                    except HomeAssistantError:
                        self.error = "frequency_release_failed"
                        await self.persist()
                        raise
                self.pending.clear()
        await self.async_refresh()

    async def async_change_settings(self, patch: dict):
        new = validate(dict(self.entry.data) | dict(self.entry.options) | patch)
        self.hass.config_entries.async_update_entry(
            self.entry, options=dict(self.entry.options) | {key: new[key] for key in patch}
        )

    async def async_reconfigure(self):
        async with self.lock:
            new = validate(dict(self.entry.data) | dict(self.entry.options))
            binding_keys = set(SOURCES) | {
                "climates",
                "indoor_sensors",
                "mains_sensors",
                "power_sensors",
                "legacy_writers",
                "room_sources",
                "ownership_reviewed",
            }
            if any(new.get(key) != self.config.get(key) for key in binding_keys):
                self.enabled = False
                self.error = "bindings_changed_review_takeover"
                self.transient = Transient()
                self.pending.clear()
            elif any(
                new[key] != self.config[key]
                for key in (
                    "room_rescue_enter",
                    "room_rescue_exit",
                    "room_rescue_seconds",
                    "room_rescue_offset",
                )
            ):
                self.transient.cold_since.clear()
                self.transient.rescue_rooms.clear()
            self.config = new
            await self.persist()
            self._listen()
        await self.async_refresh()

    async def _write(self, key: str, target: float, release: bool = False):
        if self.closing or (not self.enabled and not release):
            return
        error = self.ownership_error() or self.operating_error()
        if error:
            raise HomeAssistantError(error)
        if not release:
            latest = self._evaluate()
            if latest.targets.get(key) != target:
                await self.persist()
                return
        state = self.hass.states.get(self.config[key])
        if state is None:
            raise HomeAssistantError("Output unavailable")
        current = number(state.state)
        low, high, step = (number(state.attributes.get(k)) for k in ("min", "max", "step"))
        if (
            current is None
            or low is None
            or high is None
            or step is None
            or step <= 0
            or not low <= target <= high
            or abs((target - low) / step - round((target - low) / step)) > 1e-5
        ):
            raise HomeAssistantError("Output value or bounds unavailable/invalid")
        if (
            key == "heater_limit_entity"
            and not 0 <= target <= 6
            or key == "offset_entity"
            and not -10 <= target <= 6
            or key == "frequency_limit_entity"
            and not 17 <= target <= 120
        ):
            raise HomeAssistantError("Outside validated F1255 envelope")
        now = dt_util.utcnow().timestamp()
        pending = self.pending.get(key)
        if pending and abs(current - pending[0]) < 0.005:
            self.pending.pop(key)
            pending = None
        if pending:
            urgent = (key == "frequency_limit_entity" and target == 120 and pending[0] < 120) or (
                target < pending[0]
            )
            if not urgent:
                if now >= pending[1]:
                    raise HomeAssistantError("Pump write was not confirmed within five minutes")
                return
        if abs(current - target) < 0.005 and not pending:
            return
        before_write = Memory.restore(asdict(self.memory))
        if key == "offset_entity":
            self.memory.last_offset = now
        if key == "heater_limit_entity":
            self.memory.last_add = now
        await self.persist()
        # Recheck ownership after the persistence await and immediately before a write.
        error = self.ownership_error() or self.operating_error()
        if error or self.closing:
            raise HomeAssistantError(error or "Controller unloading")
        if not release:
            # Ignore only this proposed write's cooldown when checking new evidence.
            # A fault, stale sample or priority change during disk I/O cancels it.
            checkpoint = Memory.restore(asdict(self.memory))
            latest = self._evaluate(before_write)
            self.memory.last_offset = checkpoint.last_offset
            self.memory.last_add = checkpoint.last_add
            if latest.targets.get(key) != target:
                await self.persist()
                return
        self.pending[key] = (target, now + 300)
        try:
            await self.hass.services.async_call(
                "number",
                "set_value",
                {"entity_id": self.config[key], "value": target},
                blocking=True,
            )
        except Exception:
            self.pending.pop(key, None)
            raise

    async def _async_update_data(self):
        async with self.lock:
            if self.closing:
                return self.data or {}
            imported = True if self.enabled else self.import_legacy()
            decision = self._evaluate()
            interlock = (
                self.ownership_error()
                or self.operating_error()
                or ("legacy_state_incomplete" if not imported else None)
            )
            if self.enabled and self.hass.is_running and self.ownership_error():
                self.enabled = False
                self.error = interlock
            try:
                if not self.storage_error:
                    await self.persist()
                if self.enabled and not interlock and self.started:
                    # Re-snapshot after each await: DHW transitions and faults must not use cached targets.
                    for key in ("heater_limit_entity", "frequency_limit_entity", "offset_entity"):
                        decision = self._evaluate()
                        await self.persist()
                        if key in decision.targets:
                            await self._write(key, decision.targets[key])
                    for key, (value, deadline) in list(self.pending.items()):
                        state = self.hass.states.get(self.config[key])
                        actual = number(state.state) if state else None
                        if actual is not None and abs(actual - value) < 0.005:
                            self.pending.pop(key)
                        elif dt_util.utcnow().timestamp() >= deadline:
                            raise HomeAssistantError(
                                "Pump write was not confirmed within five minutes"
                            )
            except Exception as exc:
                LOGGER.exception("NIBE controller stopped; no further writes will be sent")
                self.enabled = False
                self.error = f"write_failed: {type(exc).__name__}"
                if not self.storage_error:
                    await self.persist()
            decision = self._evaluate()
            if not self.storage_error:
                await self.persist()
            unavailable_outputs = [
                key
                for key in OUTPUTS
                if (state := self.hass.states.get(self.config[key])) is None
                or number(state.state) is None
            ]
            return decision.data | {
                "status": "blocked"
                if self.error
                or self.storage_error
                or (self.enabled and (interlock or unavailable_outputs))
                else "active"
                if self.enabled and self.started
                else "monitor",
                "enabled": self.enabled,
                "interlock": interlock or ("output_unavailable" if unavailable_outputs else None),
                "unavailable_outputs": unavailable_outputs,
                "error": self.error,
                "migration_ready": imported,
                "pending_writes": list(self.pending),
                "memory": asdict(self.memory),
            }

    async def async_stop(self):
        self.closing = True
        if self._unsub:
            self._unsub()
            self._unsub = None
        async with self.lock:
            if not self.storage_error:
                await self.persist()
        await self.async_shutdown()
