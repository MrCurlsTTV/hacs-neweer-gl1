"""Tests for Neewer WiFi protocol helpers."""

from custom_components.neewer_wifi.const import HEARTBEAT_ACK
from custom_components.neewer_wifi.protocol import (
    build_brightness_temp_packet,
    build_handshake,
    ha_brightness_to_protocol,
    is_neewer_response,
    kelvin_to_protocol,
    protocol_brightness_to_ha,
    protocol_to_kelvin,
)


def test_build_handshake_matches_reference() -> None:
    """Handshake for 192.168.1.108 should match braintapper reference."""
    packet = build_handshake("192.168.1.108")
    assert packet.hex() == "80021000000d3139322e3136382e312e3130382e"


def test_build_brightness_temp_packet_reference() -> None:
    """Brightness 20 and 3300K (33) should match reference hex."""
    packet = build_brightness_temp_packet(20, 33)
    assert packet.hex() == "800503021421bf"


def test_is_neewer_response_heartbeat_ack() -> None:
    """Heartbeat acknowledgement is a valid Neewer response."""
    assert is_neewer_response(HEARTBEAT_ACK)


def test_is_neewer_response_rejects_invalid() -> None:
    """Random traffic should not match."""
    assert not is_neewer_response(b"")
    assert not is_neewer_response(b"GET /")


def test_brightness_and_kelvin_mapping() -> None:
    """HA brightness and kelvin mappings are reversible enough for UI."""
    assert ha_brightness_to_protocol(255) == 100
    assert protocol_brightness_to_ha(50) == 128
    assert kelvin_to_protocol(5600) == 56
    assert protocol_to_kelvin(56) == 5600
