"""Subnet discovery for Neewer WiFi lights."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.network import async_get_adapters

from .const import (
    DEFAULT_MODEL,
    DISCOVERY_CONCURRENCY,
    MAX_SCAN_DURATION,
    PROBE_TIMEOUT,
)
from .protocol import async_probe_light

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DiscoveredDevice:
    """A Neewer light discovered on the local network."""

    host: str
    unique_id: str
    name: str
    model: str = DEFAULT_MODEL
    client_ip: str = ""


def _is_private_ipv4(address: str) -> bool:
    """Return True if the address is a private RFC1918 IPv4 host."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.version == 4 and ip.is_private and not ip.is_loopback


def _hosts_for_network(network: ipaddress.IPv4Network) -> list[str]:
    """Enumerate assignable host addresses for a network."""
    if network.num_addresses <= 2:
        return []
    return [str(host) for host in network.hosts()]


async def async_get_local_networks(hass: HomeAssistant) -> list[tuple[str, ipaddress.IPv4Network]]:
    """Return (client_ip, network) pairs for private IPv4 adapters."""
    adapters = await async_get_adapters(hass)
    networks: list[tuple[str, ipaddress.IPv4Network]] = []
    seen: set[str] = set()

    for adapter in adapters:
        for ipv4 in adapter["ipv4"]:
            address = ipv4["address"]
            if not _is_private_ipv4(address):
                continue
            prefix = ipv4.get("network_prefix")
            if prefix is None:
                continue
            try:
                network = ipaddress.IPv4Network(
                    (address, prefix),
                    strict=False,
                )
            except ValueError:
                continue
            key = f"{address}/{network.prefixlen}"
            if key in seen:
                continue
            seen.add(key)
            networks.append((address, network))

    if not networks:
        _LOGGER.debug("No private IPv4 adapters found for discovery")
    return networks


def client_ip_for_host(
    host: str,
    networks: list[tuple[str, ipaddress.IPv4Network]],
) -> str | None:
    """Pick the local client IP on the same subnet as the target host."""
    try:
        target = ipaddress.ip_address(host)
    except ValueError:
        return None
    for client_ip, network in networks:
        if target in network:
            return client_ip
    return networks[0][0] if networks else None


async def async_discover_neewer_lights(
    hass: HomeAssistant,
    *,
    hosts: list[str] | None = None,
    exclude_hosts: set[str] | None = None,
) -> list[DiscoveredDevice]:
    """
    Discover Neewer WiFi lights by UDP handshake probing on port 5052.

    When hosts is omitted, all hosts on local private subnets are scanned.
    """
    exclude = exclude_hosts or set()
    local_networks = await async_get_local_networks(hass)

    if hosts is None:
        candidate_hosts: list[str] = []
        for _client_ip, network in local_networks:
            candidate_hosts.extend(_hosts_for_network(network))
    else:
        candidate_hosts = list(hosts)

    candidate_hosts = [
        host
        for host in dict.fromkeys(candidate_hosts)
        if _is_private_ipv4(host) and host not in exclude
    ]

    if not candidate_hosts:
        return []

    _LOGGER.debug(
        "Starting Neewer discovery across %d candidate hosts", len(candidate_hosts)
    )

    semaphore = asyncio.Semaphore(DISCOVERY_CONCURRENCY)
    discovered: dict[str, DiscoveredDevice] = {}
    scan_started = asyncio.get_running_loop().time()

    async def _probe(host: str) -> None:
        if asyncio.get_running_loop().time() - scan_started > MAX_SCAN_DURATION:
            return
        client_ip = client_ip_for_host(host, local_networks)
        if client_ip is None:
            return
        async with semaphore:
            try:
                found = await async_probe_light(
                    host,
                    client_ip,
                    timeout=PROBE_TIMEOUT,
                )
            except OSError as err:
                _LOGGER.debug("Probe error for %s: %s", host, err)
                return
            if found:
                unique_id = f"neewer_wifi_{host.replace('.', '_')}"
                name = f"{DEFAULT_MODEL} @ {host}"
                discovered[host] = DiscoveredDevice(
                    host=host,
                    unique_id=unique_id,
                    name=name,
                    client_ip=client_ip,
                )
                _LOGGER.debug("Discovered Neewer light at %s", host)

    await asyncio.gather(*(_probe(host) for host in candidate_hosts))

    return sorted(discovered.values(), key=lambda device: ipaddress.ip_address(device.host))
