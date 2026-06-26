"""Tests for Neewer WiFi discovery helpers."""

import ipaddress

from custom_components.neewer_wifi.discovery import (
    _hosts_for_network,
    _hex_be_word_to_ipv4,
    _is_private_ipv4,
    _prefixlen_from_route_mask,
    client_ip_for_host,
    client_ip_for_network,
    parse_ipv4_network,
    parse_proc_net_route,
)


def test_is_private_ipv4() -> None:
    """Private host detection."""
    assert _is_private_ipv4("192.168.1.10")
    assert not _is_private_ipv4("8.8.8.8")
    assert not _is_private_ipv4("127.0.0.1")


def test_hosts_for_network_sl24() -> None:
    """A /24 should yield 254 hosts."""
    network = ipaddress.IPv4Network("192.168.1.0/24")
    hosts = _hosts_for_network(network)
    assert len(hosts) == 254
    assert hosts[0] == "192.168.1.1"
    assert hosts[-1] == "192.168.1.254"


def test_client_ip_for_host_same_subnet() -> None:
    """Client IP should be on the same subnet as the light."""
    networks = [
        (
            "192.168.1.50",
            ipaddress.IPv4Network("192.168.1.0/24"),
        ),
        (
            "10.0.0.5",
            ipaddress.IPv4Network("10.0.0.0/24"),
        ),
    ]
    assert client_ip_for_host("192.168.1.142", networks) == "192.168.1.50"
    assert client_ip_for_host("10.0.0.20", networks) == "10.0.0.5"


def test_client_ip_for_host_cross_subnet_returns_none() -> None:
    """Hosts outside known subnets should not use a fallback client IP."""
    networks = [
        (
            "192.168.1.50",
            ipaddress.IPv4Network("192.168.1.0/24"),
        ),
    ]
    assert client_ip_for_host("192.168.103.101", networks) is None


def test_parse_ipv4_network_cidr() -> None:
    """CIDR subnets should parse directly."""
    network = parse_ipv4_network("192.168.103.0/24")
    assert network.prefixlen == 24
    assert str(network.network_address) == "192.168.103.0"


def test_parse_ipv4_network_bare_ip() -> None:
    """Bare IPv4 addresses should assume /24."""
    network = parse_ipv4_network("192.168.103.1")
    assert network.prefixlen == 24


def test_client_ip_for_network_overlap() -> None:
    """Overlapping networks should return the matching client IP."""
    networks = [
        (
            "192.168.103.50",
            ipaddress.IPv4Network("192.168.103.0/24"),
        ),
    ]
    scan_network = ipaddress.IPv4Network("192.168.103.0/24")
    assert client_ip_for_network(scan_network, networks) == "192.168.103.50"


def test_hex_be_word_to_ipv4() -> None:
    """Route table addresses are little-endian hex words."""
    assert _hex_be_word_to_ipv4("0067A8C0") == "192.168.103.0"
    assert _hex_be_word_to_ipv4("0167A8C0") == "192.168.103.1"


def test_prefixlen_from_route_mask() -> None:
    """Route masks map to CIDR prefix lengths."""
    assert _prefixlen_from_route_mask("00FFFFFF") == 24


def test_parse_proc_net_route_private_network() -> None:
    """Private connected routes should be parsed for discovery."""
    content = """Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT
enp16s0\t0067A8C0\t00000000\t0001\t0\t0\t100\t00FFFFFF\t0\t0\t0
enp16s0\t00000000\t0167A8C0\t0003\t0\t0\t100\t00000000\t0\t0\t0
docker0\t000011AC\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0
"""
    routes = parse_proc_net_route(content)
    assert len(routes) == 1
    assert routes[0].iface == "enp16s0"
    assert str(routes[0].network) == "192.168.103.0/24"
    assert routes[0].gateway == "0.0.0.0"


def test_parse_proc_net_route_skips_broader_than_sl16() -> None:
    """Routes broader than /16 should not be scanned."""
    content = """Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT
enp16s0\t0000000A\t00000000\t0001\t0\t0\t100\t000000FF\t0\t0\t0
enp16s0\t000010AC\t00000000\t0001\t0\t0\t100\t0000FFFF\t0\t0\t0
"""
    routes = parse_proc_net_route(content)
    assert len(routes) == 1
    assert str(routes[0].network) == "172.16.0.0/16"
