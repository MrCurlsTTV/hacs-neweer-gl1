"""Pytest configuration — mock Home Assistant for unit tests."""

import asyncio
import ipaddress
import sys
import types
from unittest.mock import MagicMock

import pytest

_HA = MagicMock()
sys.modules.setdefault("homeassistant", _HA)
sys.modules.setdefault("homeassistant.config_entries", MagicMock())
sys.modules.setdefault("homeassistant.const", MagicMock())
sys.modules.setdefault("homeassistant.core", MagicMock())
sys.modules.setdefault("homeassistant.data_entry_flow", MagicMock())
sys.modules.setdefault("homeassistant.exceptions", MagicMock())
sys.modules.setdefault("homeassistant.helpers", MagicMock())
sys.modules.setdefault("homeassistant.helpers.entity_platform", MagicMock())
sys.modules.setdefault("homeassistant.helpers.network", MagicMock())
sys.modules.setdefault("homeassistant.helpers.selector", MagicMock())
sys.modules.setdefault("homeassistant.helpers.update_coordinator", MagicMock())
sys.modules.setdefault("homeassistant.components.light", MagicMock())
sys.modules.setdefault("homeassistant.components.network", MagicMock())


class _HomeAssistantError(Exception):
    """Stand-in so integration exceptions are real, catchable exception types."""


class _DataUpdateCoordinator:
    """Stand-in base so coordinator methods can be called in tests."""

    def __class_getitem__(cls, _item):
        return cls

    def __init__(self, *_args, **_kwargs) -> None:
        pass


sys.modules["homeassistant.helpers.update_coordinator"].DataUpdateCoordinator = (
    _DataUpdateCoordinator
)


class _ConfigFlow:
    """Stand-in base accepting the `domain=` class keyword."""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__()


sys.modules["homeassistant.exceptions"].HomeAssistantError = _HomeAssistantError
sys.modules["homeassistant.config_entries"].ConfigFlow = _ConfigFlow


ROUTE_HEADER = (
    "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
)


def _hex_le(address: str) -> str:
    """Encode an IPv4 address the way /proc/net/route does."""
    return int.from_bytes(ipaddress.IPv4Address(address).packed, "little").to_bytes(
        4, "big"
    ).hex().upper()


def route_line(iface: str, network: str, gateway: str = "0.0.0.0") -> str:
    net = ipaddress.IPv4Network(network)
    return (
        f"{iface}\t{_hex_le(str(net.network_address))}\t{_hex_le(gateway)}\t0003\t0\t0\t100\t"
        f"{_hex_le(str(net.netmask))}\t0\t0\t0\n"
    )


class FakeHass:
    async def async_add_executor_job(self, func, *args):
        return func(*args)


@pytest.fixture
def system(monkeypatch, tmp_path):
    """Fake host networking: HA adapters, routing table, iface IPs, kernel route."""
    state = types.SimpleNamespace(
        adapters=[],
        routes=[],
        iface_ips={},
        kernel_src={},
    )

    async def fake_get_adapters(_hass):
        return [
            {
                "enabled": True,
                "ipv4": [
                    {"address": addr, "network_prefix": prefix}
                    for addr, prefix in state.adapters
                ],
            }
        ]

    route_file = tmp_path / "route"

    def write_routes():
        route_file.write_text(ROUTE_HEADER + "".join(state.routes), encoding="utf-8")

    class _FakeSocket:
        def __init__(self, *_args, **_kwargs):
            self._src = None

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def connect(self, addr):
            if addr[0] not in state.kernel_src:
                raise OSError("Network is unreachable")
            self._src = state.kernel_src[addr[0]]

        def getsockname(self):
            return (self._src, 40000)

    fake_ifaddr = types.ModuleType("ifaddr")
    fake_ifaddr.get_adapters = lambda: [
        types.SimpleNamespace(
            name=name,
            ips=[types.SimpleNamespace(ip=ip, is_IPv6=False) for ip in ips],
        )
        for name, ips in state.iface_ips.items()
    ]

    from custom_components.neewer_wifi import discovery

    monkeypatch.setattr(discovery, "async_get_adapters", fake_get_adapters)
    monkeypatch.setattr(discovery, "PROC_NET_ROUTE", str(route_file))
    fake_socket_mod = types.SimpleNamespace(
        socket=_FakeSocket, AF_INET=discovery.socket.AF_INET, SOCK_DGRAM=discovery.socket.SOCK_DGRAM
    )
    monkeypatch.setattr(discovery, "socket", fake_socket_mod)
    monkeypatch.setitem(sys.modules, "ifaddr", fake_ifaddr)

    def resolve(host: str):
        write_routes()
        return asyncio.run(discovery.async_resolve_client_ip(FakeHass(), host))

    state.resolve = resolve
    state.write_routes = write_routes
    return state
