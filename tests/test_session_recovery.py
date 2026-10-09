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


HOST = "192.168.16.101"


def _wired_protocol(monkeypatch, *, light_acks: bool) -> NeewerProtocol:
    """A protocol whose fake transport acks heartbeats only if light_acks."""
    import custom_components.neewer_wifi.protocol as protocol_module

    real_sleep = asyncio.sleep

    async def fast_sleep(_delay):
        await real_sleep(0)

    monkeypatch.setattr(protocol_module.asyncio, "sleep", fast_sleep)
    monkeypatch.setattr(protocol_module, "HANDSHAKE_ACK_TIMEOUT", 0.05)

    protocol = _protocol()
    transport = MagicMock()

    def sendto(data, addr):
        if light_acks and data == protocol_module.HEARTBEAT_PACKET:
            protocol.datagram_received(protocol_module.HEARTBEAT_ACK, addr)

    transport.sendto.side_effect = sendto
    protocol.transport = transport
    return protocol


def test_connect_without_ack_fails_and_light_is_unavailable(monkeypatch) -> None:
    """A light that never answers must not look connected."""

    async def scenario():
        protocol = _wired_protocol(monkeypatch, light_acks=False)
        with pytest.raises(TimeoutError):
            await protocol.async_connect(HOST, "192.168.16.51")
        assert not protocol.is_available(HOST)
        with pytest.raises(HomeAssistantError):
            await protocol.async_power_on(HOST)

    asyncio.run(scenario())


def test_connect_with_ack_makes_light_available(monkeypatch) -> None:
    """An acked handshake leaves the light connected and available."""

    async def scenario():
        protocol = _wired_protocol(monkeypatch, light_acks=True)
        await protocol.async_connect(HOST, "192.168.16.51")
        assert protocol.is_available(HOST)
        await protocol.async_power_on(HOST)

    asyncio.run(scenario())


def test_commands_rejected_once_heartbeat_acks_stop(monkeypatch) -> None:
    """A connected light that stops answering is unavailable and refuses commands."""

    async def scenario():
        protocol = _wired_protocol(monkeypatch, light_acks=True)
        await protocol.async_connect(HOST, "192.168.16.51")
        protocol._sessions[HOST].last_heartbeat_ack = -1e9
        assert not protocol.is_available(HOST)
        with pytest.raises(HomeAssistantError):
            await protocol.async_set_brightness_temp(HOST, 50, 50)

    asyncio.run(scenario())


def test_availability_listener_fires_only_on_change(monkeypatch) -> None:
    """Listeners hear about a light going unavailable once, not on every tick."""

    async def scenario():
        protocol = _wired_protocol(monkeypatch, light_acks=True)
        calls = []
        protocol.add_availability_listener(HOST, lambda: calls.append(1))
        await protocol.async_connect(HOST, "192.168.16.51")
        protocol._notify_availability()
        protocol._notify_availability()
        assert len(calls) == 1
        protocol._sessions[HOST].last_heartbeat_ack = -1e9
        protocol._notify_availability()
        protocol._notify_availability()
        assert len(calls) == 2

    asyncio.run(scenario())


def _bare_coordinator(protocol):
    from custom_components.neewer_wifi.coordinator import NeewerLightState

    coordinator = object.__new__(NeewerDataUpdateCoordinator)
    coordinator.protocol = protocol
    coordinator.host = HOST
    coordinator._state = NeewerLightState()
    coordinator.async_update_listeners = MagicMock()
    return coordinator


def test_failed_command_does_not_change_light_state() -> None:
    """If the light cannot be reached, HA's state must not claim it changed."""
    protocol = MagicMock()
    error = HomeAssistantError("not responding")
    protocol.async_power_on = AsyncMock(side_effect=error)
    protocol.async_power_off = AsyncMock(side_effect=error)
    protocol.async_set_brightness_temp = AsyncMock(side_effect=error)
    coordinator = _bare_coordinator(protocol)

    with pytest.raises(HomeAssistantError):
        asyncio.run(coordinator.async_turn_on(brightness=200))
    assert coordinator._state.is_on is False
    assert coordinator._state.brightness == _bare_coordinator(protocol)._state.brightness

    coordinator._state.is_on = True
    with pytest.raises(HomeAssistantError):
        asyncio.run(coordinator.async_turn_off())
    assert coordinator._state.is_on is True

    with pytest.raises(HomeAssistantError):
        asyncio.run(coordinator.async_set_brightness(50))
    coordinator.async_update_listeners.assert_not_called()


def test_parallel_setup_binds_once_and_starts_one_heartbeat() -> None:
    """Two entries calling async_setup at once must share one socket and one loop."""

    async def scenario():
        hass = MagicMock()
        hass.loop = asyncio.get_running_loop()
        protocol = NeewerProtocol(hass)
        binds = []

        async def fake_endpoint(factory, **_kwargs):
            binds.append(1)
            await asyncio.sleep(0)
            protocol.connection_made(MagicMock())
            return MagicMock(), protocol

        hass.loop.create_datagram_endpoint = fake_endpoint
        protocol._heartbeat_loop = AsyncMock()
        await asyncio.gather(protocol.async_setup(), protocol.async_setup())
        assert len(binds) == 1

        await protocol.async_close()
        await protocol.async_setup()
        assert len(binds) == 2

    asyncio.run(scenario())
