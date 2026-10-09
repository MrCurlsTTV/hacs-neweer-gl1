"""Tests for manual-setup host validation and the errors shown to the user."""

import asyncio
import errno

import pytest

from custom_components.neewer_wifi import config_flow
from tests.conftest import FakeHass, route_line

LIGHT = "192.168.103.101"


@pytest.fixture
def routed_light(system, monkeypatch):
    """A light on a routed subnet; the probe outcome is set per test."""
    system.adapters = [("192.168.1.50", 24)]
    system.routes = [route_line("enp1s0", "192.168.103.0/24", gateway="192.168.1.2")]
    system.iface_ips = {"enp1s0": ["192.168.1.50"]}
    system.kernel_src = {LIGHT: "192.168.1.50"}
    system.probe = lambda host, client_ip: True

    async def fake_probe(host, client_ip, *_args, **_kwargs):
        return system.probe(host, client_ip)

    monkeypatch.setattr(config_flow, "async_probe_light", fake_probe)

    def validate(host: str = LIGHT):
        system.write_routes()
        return asyncio.run(config_flow._async_validate_host(FakeHass(), host))

    system.validate = validate
    return system


def test_silent_light_reports_no_response_with_client_ip(routed_light) -> None:
    """The light usually just stays silent; say so and show which client IP was embedded."""
    routed_light.probe = lambda host, client_ip: False

    with pytest.raises(config_flow.ValidationError) as exc_info:
        routed_light.validate()

    assert exc_info.value.error_key == "no_response"
    assert exc_info.value.placeholders == {"host": LIGHT, "client_ip": "192.168.1.50"}


def _raise(err_no: int):
    def probe(host, client_ip):
        raise OSError(err_no, "boom")

    return probe


def test_udp_port_already_taken_reports_port_in_use(routed_light) -> None:
    """Another app (e.g. the Neewer desktop app) holding UDP 5052 gets a specific error."""
    routed_light.probe = _raise(errno.EADDRINUSE)

    with pytest.raises(config_flow.ValidationError) as exc_info:
        routed_light.validate()

    assert exc_info.value.error_key == "port_in_use"
    assert exc_info.value.placeholders == {"port": "5052"}


@pytest.mark.parametrize("err_no", [errno.ENETUNREACH, errno.EHOSTUNREACH])
def test_no_route_to_light_reports_host_unreachable(routed_light, err_no) -> None:
    """A missing route or ICMP unreachable points at routing, not at the light."""
    routed_light.probe = _raise(err_no)

    with pytest.raises(config_flow.ValidationError) as exc_info:
        routed_light.validate()

    assert exc_info.value.error_key == "host_unreachable"
    assert exc_info.value.placeholders == {"host": LIGHT, "client_ip": "192.168.1.50"}


def test_light_with_no_route_reports_cannot_determine_client_ip(routed_light) -> None:
    """No adapter, route table entry or kernel route reaches the light."""
    routed_light.routes = []
    routed_light.kernel_src = {}

    with pytest.raises(config_flow.ValidationError) as exc_info:
        routed_light.validate()

    assert exc_info.value.error_key == "cannot_determine_client_ip"
    assert exc_info.value.placeholders == {"host": LIGHT}


def test_non_ip_host_reports_invalid_host(routed_light) -> None:
    with pytest.raises(config_flow.ValidationError) as exc_info:
        routed_light.validate("neewer.local")

    assert exc_info.value.error_key == "invalid_host"


def test_reachable_light_embeds_kernel_source_ip(routed_light) -> None:
    """On success the stored client IP is the one the handshake actually used."""
    used = {}

    def probe(host, client_ip):
        used["client_ip"] = client_ip
        return True

    routed_light.probe = probe

    device = routed_light.validate()

    assert device.host == LIGHT
    assert device.client_ip == used["client_ip"] == "192.168.1.50"
