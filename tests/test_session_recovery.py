"""Tests for dropped-session recovery and client IP precedence."""

import asyncio
import types
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.neewer_wifi import coordinator as coordinator_module
from custom_components.neewer_wifi.coordinator import NeewerDataUpdateCoordinator
from custom_components.neewer_wifi.protocol import NeewerProtocol


def _protocol() -> NeewerProtocol:
    return NeewerProtocol(MagicMock())


def test_command_on_unconnected_light_raises_ha_error() -> None:
    """A light without a live session fails with a clean HA error, not RuntimeError."""
    protocol = _protocol()
    with pytest.raises(HomeAssistantError):
        asyncio.run(protocol.async_power_on("192.168.16.101"))


def test_heartbeat_loop_retries_a_dropped_session() -> None:
    """A session left disconnected by a failed send or reconnect is reconnected."""

    async def scenario() -> list[tuple[str, str]]:
        protocol = _protocol()
        protocol.async_connect = AsyncMock()
        session = protocol.register_light("192.168.16.101", "192.168.16.51")
        session.connected = False
        session.last_connect_attempt = -1e9
        task = asyncio.create_task(protocol._heartbeat_loop())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return [call.args for call in protocol.async_connect.await_args_list]

    assert asyncio.run(scenario()) == [("192.168.16.101", "192.168.16.51")]


def test_heartbeat_loop_waits_between_reconnect_attempts() -> None:
    """A recent failed attempt is not hammered again straight away."""

    async def scenario() -> int:
        protocol = _protocol()
        protocol.async_connect = AsyncMock()
        session = protocol.register_light("192.168.16.101", "192.168.16.51")
        session.connected = False
        session.last_connect_attempt = asyncio.get_running_loop().time()
        task = asyncio.create_task(protocol._heartbeat_loop())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return protocol.async_connect.await_count

    assert asyncio.run(scenario()) == 0


def _coordinator(stored_ip):
    return types.SimpleNamespace(
        hass=MagicMock(),
        host="192.168.16.101",
        entry=types.SimpleNamespace(data={"client_ip": stored_ip} if stored_ip else {}),
    )


def test_client_ip_prefers_current_route_over_stored(monkeypatch) -> None:
    """A stale stored client IP must not override what the kernel would send from."""
    monkeypatch.setattr(
        coordinator_module, "async_resolve_client_ip", AsyncMock(return_value="192.168.16.51")
    )
    result = asyncio.run(
        NeewerDataUpdateCoordinator._async_resolve_client_ip(_coordinator("192.168.103.146"))
    )
    assert result == "192.168.16.51"


def test_client_ip_falls_back_to_stored(monkeypatch) -> None:
    """If routing cannot be resolved, the stored client IP is still used."""
    monkeypatch.setattr(
        coordinator_module, "async_resolve_client_ip", AsyncMock(return_value=None)
    )
    result = asyncio.run(
        NeewerDataUpdateCoordinator._async_resolve_client_ip(_coordinator("192.168.16.51"))
    )
    assert result == "192.168.16.51"
