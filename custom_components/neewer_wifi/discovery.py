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


def parse_ipv4_network(subnet: str) -> ipaddress.IPv4Network:
    """Parse a CIDR string or bare IPv4 address (/24 assumed)."""
    subnet = subnet.strip()
    if not subnet:
        raise ValueError("empty subnet")
    if "/" not in subnet:
        subnet = f"{subnet}/24"
    return ipaddress.IPv4Network(subnet, strict=False)


def client_ip_for_network(
    network: ipaddress.IPv4Network,
    networks: list[tuple[str, ipaddress.IPv4Network]],
) -> str | None:
    """Return the Home Assistant client IP on the same network as scan_network."""
    for client_ip, local_net in networks:
        if network.overlaps(local_net):
            return client_ip
        try:
            if ipaddress.ip_address(client_ip) in network:
                return client_ip
        except ValueError:
            continue
    return None


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
        _LOGGER.warning("No private IPv4 adapters found for discovery")
    else:
        _LOGGER.info(
            "Local adapters for discovery: %s",
            ", ".join(f"{addr}/{net.prefixlen}" for addr, net in networks),
        )
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
    return None


async def async_discover_neewer_lights(
    hass: HomeAssistant,
    *,
    hosts: list[str] | None = None,
    scan_networks: list[ipaddress.IPv4Network] | None = None,
    client_ip_override: str | None = None,
    exclude_hosts: set[str] | None = None,
) -> list[DiscoveredDevice]:
    """
    Discover Neewer WiFi lights by UDP handshake probing on port 5052.

    When hosts is omitted, all hosts on local private subnets are scanned.
    scan_networks limits discovery to specific subnets.
    """
    exclude = exclude_hosts or set()
    local_networks = await async_get_local_networks(hass)

    if hosts is not None:
        candidate_hosts = list(hosts)
    elif scan_networks is not None:
        candidate_hosts = []
        for network in scan_networks:
            candidate_hosts.extend(_hosts_for_network(network))
    else:
        candidate_hosts = []
        for _client_ip, network in local_networks:
            candidate_hosts.extend(_hosts_for_network(network))

    candidate_hosts = [
        host
        for host in dict.fromkeys(candidate_hosts)
        if _is_private_ipv4(host) and host not in exclude
    ]

    if not candidate_hosts:
        _LOGGER.info("No candidate hosts to scan for Neewer lights")
        return []

    scan_label = (
        ", ".join(str(network) for network in scan_networks)
        if scan_networks
        else "local adapters"
    )
    _LOGGER.info(
        "Starting Neewer discovery on %s (%d hosts, client IP %s)",
        scan_label,
        len(candidate_hosts),
        client_ip_override or "per-host",
    )

    semaphore = asyncio.Semaphore(DISCOVERY_CONCURRENCY)
    discovered: dict[str, DiscoveredDevice] = {}
    scan_started = asyncio.get_running_loop().time()
    skipped_no_client_ip = 0
    probe_errors = 0

    async def _probe(host: str) -> None:
        nonlocal skipped_no_client_ip, probe_errors
        if asyncio.get_running_loop().time() - scan_started > MAX_SCAN_DURATION:
            return
        client_ip = client_ip_override or client_ip_for_host(host, local_networks)
        if client_ip is None:
            skipped_no_client_ip += 1
            _LOGGER.debug("Skipping %s: no client IP on matching subnet", host)
            return
        async with semaphore:
            try:
                found = await async_probe_light(
                    host,
                    client_ip,
                    timeout=PROBE_TIMEOUT,
                )
            except OSError as err:
                probe_errors += 1
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
                _LOGGER.info("Discovered Neewer light at %s (client IP %s)", host, client_ip)

    await asyncio.gather(*(_probe(host) for host in candidate_hosts))

    elapsed = asyncio.get_running_loop().time() - scan_started
    _LOGGER.info(
        "Neewer discovery finished in %.1fs: %d found, %d skipped (no client IP), %d probe errors",
        elapsed,
        len(discovered),
        skipped_no_client_ip,
        probe_errors,
    )

    return sorted(discovered.values(), key=lambda device: ipaddress.ip_address(device.host))
