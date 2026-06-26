"""Tests for Neewer WiFi discovery helpers."""

import ipaddress

from custom_components.neewer_wifi.discovery import (
    _hosts_for_network,
    _is_private_ipv4,
    client_ip_for_host,
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
