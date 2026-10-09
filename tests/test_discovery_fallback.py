"""Tests for the all-interfaces discovery fallback."""

import asyncio
import ipaddress

import pytest

from custom_components.neewer_wifi import discovery
from tests.conftest import FakeHass


def _net(cidr: str) -> ipaddress.IPv4Network:
    return ipaddress.IPv4Network(cidr)


@pytest.fixture
def scan(monkeypatch):
    """Fake the normal targets, extra interfaces and which hosts answer a probe."""
    state = type("State", (), {})()
    state.primary = [("192.168.1.50", _net("192.168.1.0/30"))]
    state.interfaces = []
    state.lights = set()
    state.probed = []

    async def fake_local_networks(_hass):
        return list(state.primary)

    async def fake_targets(_hass):
        return [
            discovery.DiscoveryTarget(network=net, client_ip=ip, source="adapter")
            for ip, net in state.primary
        ]

    async def fake_probe(host, client_ip, timeout=2.0):
        state.probed.append((host, client_ip))
        return host in state.lights

    monkeypatch.setattr(discovery, "async_get_local_networks", fake_local_networks)
    monkeypatch.setattr(discovery, "async_get_discovery_targets", fake_targets)
    monkeypatch.setattr(discovery, "_get_all_interface_networks", lambda: state.interfaces)
    monkeypatch.setattr(discovery, "async_probe_light", fake_probe)

    def run(**kwargs):
        return asyncio.run(discovery.async_discover_neewer_lights(FakeHass(), **kwargs))

    state.run = run
    return state


def test_fallback_targets_skip_scanned_and_put_small_subnets_first(monkeypatch) -> None:
    """Already-scanned subnets are dropped and the smallest subnets come first."""
    discovery_pairs = [
        ("192.168.1.50", _net("192.168.1.0/24")),
        ("10.0.0.5", _net("10.0.0.0/16")),
        ("192.168.16.30", _net("192.168.16.0/24")),
    ]
    monkeypatch.setattr(discovery, "_get_all_interface_networks", lambda: discovery_pairs)
    targets = asyncio.run(
        discovery.async_get_fallback_targets(FakeHass(), {"192.168.1.0/24"})
    )
    assert [str(t.network) for t in targets] == ["192.168.16.0/24", "10.0.0.0/16"]
    assert targets[0].client_ip == "192.168.16.30"
    assert all(t.source == "interface" for t in targets)


def test_fallback_finds_light_on_other_interface(scan) -> None:
    """Nothing on the normal targets: the other interface's subnet is scanned."""
    scan.interfaces = [("192.168.16.30", _net("192.168.16.0/30"))]
    scan.lights = {"192.168.16.1"}

    found = scan.run()

    assert [(d.host, d.client_ip) for d in found] == [("192.168.16.1", "192.168.16.30")]


def test_no_fallback_when_normal_scan_finds_a_light(scan) -> None:
    """A hit on the normal targets means other interfaces are not probed."""
    scan.interfaces = [("192.168.16.30", _net("192.168.16.0/30"))]
    scan.lights = {"192.168.1.1"}

    found = scan.run()

    assert [d.host for d in found] == ["192.168.1.1"]
    assert not any(host.startswith("192.168.16.") for host, _ in scan.probed)


def test_fallback_does_not_rescan_normal_subnets(scan) -> None:
    """An interface on a subnet already scanned is not probed a second time."""
    scan.interfaces = [("192.168.1.50", _net("192.168.1.0/30"))]

    assert scan.run() == []
    assert len(scan.probed) == len({host for host, _ in scan.probed})


def test_explicit_subnet_never_falls_back(scan) -> None:
    """A subnet the user typed is the only thing scanned."""
    scan.interfaces = [("192.168.16.30", _net("192.168.16.0/30"))]
    scan.lights = {"192.168.16.1"}

    found = scan.run(
        scan_networks=[_net("192.168.1.0/30")], client_ip_override="192.168.1.50"
    )

    assert found == []
    assert not any(host.startswith("192.168.16.") for host, _ in scan.probed)
