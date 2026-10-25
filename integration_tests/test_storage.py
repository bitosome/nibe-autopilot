"""Durability checks exercise the native HA Store save wrapper."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import CoreState
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store

from custom_components.nibe_autopilot.storage import StrictStore


async def test_cancelled_save_cannot_release_the_disk_write_lock_early(hass):
    store = StrictStore(hass, 1, "nibe.test")
    started, finish = asyncio.Event(), asyncio.Event()
    written = []

    async def write(data):
        if data["data"]["value"] == 1:
            started.set()
            await finish.wait()
        written.append(data["data"]["value"])

    with patch.object(Store, "_async_write_data", AsyncMock(side_effect=write)):
        first = asyncio.create_task(store.async_save({"value": 1}))
        await started.wait()
        first.cancel()
        second = asyncio.create_task(store.async_save({"value": 2}))
        await asyncio.sleep(0)
        first.cancel()
        await asyncio.sleep(0)
        assert not written and not second.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        await second
    assert written == [1, 2]


async def test_stopping_cannot_acknowledge_deferred_safety_state(hass):
    store = StrictStore(hass, 1, "nibe.test")
    with patch.object(hass, "state", CoreState.stopping):
        with pytest.raises(HomeAssistantError):
            await store.async_save({"hold": True})


@pytest.mark.parametrize("content", ["{}", "null", "invalid-json"])
async def test_corrupt_envelope_cannot_reset_holds(hass, tmp_path, content):
    hass.config.config_dir = str(tmp_path)
    store = StrictStore(hass, 1, "nibe.test")
    path = Path(store.path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    with pytest.raises(HomeAssistantError):
        await store.async_load()
    with pytest.raises(HomeAssistantError):
        await store.async_save({"memory": {}})
    assert path.read_text() == content
