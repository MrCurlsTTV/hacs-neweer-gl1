"""Config flow for Neewer WiFi."""

from __future__ import annotations

import ipaddress
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

from .const import CONF_CLIENT_IP, CONF_SUBNET, DOMAIN
from .discovery import (
    async_discover_neewer_lights,
    async_get_local_networks,
    async_resolve_client_ip,
    client_ip_for_host,
    client_ip_for_network,
    DiscoveredDevice,
    parse_ipv4_network,
)
from .protocol import async_probe_light

_LOGGER = logging.getLogger(__name__)

STEP_MANUAL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
    }
)


async def _async_get_configured_hosts(hass: HomeAssistant) -> set[str]:
    """Return hosts already configured."""
    return {
        entry.data[CONF_HOST]
        for entry in hass.config_entries.async_entries(DOMAIN)
    }


async def _async_validate_host(hass: HomeAssistant, host: str) -> DiscoveredDevice:
    """Probe a host and return device info when valid."""
    host = host.strip()
    try:
        ipaddress.ip_address(host)
    except ValueError as err:
        raise InvalidHost from err

    networks = await async_get_local_networks(hass)
    client_ip = client_ip_for_host(host, networks)
    if client_ip is None:
        client_ip = await async_resolve_client_ip(hass, host)
    if client_ip is None:
        _LOGGER.warning(
            "No local network adapter found for light %s (adapters: %s)",
            host,
            [f"{addr}/{net.prefixlen}" for addr, net in networks],
        )
        raise CannotDetermineClientIp

    _LOGGER.info("Probing light at %s using client IP %s", host, client_ip)
    try:
        found = await async_probe_light(host, client_ip)
    except OSError as err:
        _LOGGER.warning("Probe failed for %s: %s", host, err)
        raise CannotConnect from err
    if not found:
        _LOGGER.warning("No Neewer response from %s", host)
        raise CannotConnect

    _LOGGER.info("Validated Neewer light at %s (client IP %s)", host, client_ip)
    unique_id = f"neewer_wifi_{host.replace('.', '_')}"
    return DiscoveredDevice(
        host=host,
        unique_id=unique_id,
        name=f"Neewer GL1 Pro @ {host}",
        client_ip=client_ip,
    )


def _entry_data(device: DiscoveredDevice) -> dict[str, str]:
    """Build config entry data for a device."""
    return {
        CONF_HOST: device.host,
        CONF_CLIENT_IP: device.client_ip,
    }


def _device_picker_schema(
    discovered: dict[str, DiscoveredDevice],
) -> vol.Schema:
    """Build the multi-select schema for discovered lights."""
    options = [
        selector.SelectOptionDict(value=host, label=device.name)
        for host, device in discovered.items()
    ]
    return vol.Schema(
        {
            vol.Required("devices"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    mode=selector.SelectSelectorMode.LIST,
                    multiple=True,
                )
            ),
        }
    )


def _subnet_retry_schema() -> vol.Schema:
    """Build the schema shown when discovery finds no lights."""
    return vol.Schema(
        {
            vol.Optional(CONF_SUBNET): str,
        }
    )


class NeewerWifiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Neewer WiFi."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered: dict[str, DiscoveredDevice] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Present discovery or manual setup."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["discover", "manual"],
            description_placeholders={},
        )

    async def _async_run_discovery(
        self,
        configured_hosts: set[str],
        *,
        scan_networks: list[ipaddress.IPv4Network] | None = None,
        client_ip_override: str | None = None,
    ) -> FlowResult:
        """Scan for lights and show the picker or subnet retry form."""
        if scan_networks:
            _LOGGER.info(
                "Starting Neewer discovery on subnet(s): %s",
                ", ".join(str(network) for network in scan_networks),
            )
        else:
            _LOGGER.info("Starting Neewer discovery on local adapters")

        self._discovered = {}
        discovered = await async_discover_neewer_lights(
            self.hass,
            scan_networks=scan_networks,
            client_ip_override=client_ip_override,
            exclude_hosts=configured_hosts,
        )
        for device in discovered:
            self._discovered[device.host] = device

        if not self._discovered:
            _LOGGER.info("Neewer discovery finished with no lights found")
            return self.async_show_form(
                step_id="discover",
                data_schema=_subnet_retry_schema(),
                errors={"base": "no_devices_found"},
                description_placeholders={},
            )

        _LOGGER.info(
            "Neewer discovery found %d light(s): %s",
            len(self._discovered),
            ", ".join(self._discovered),
        )
        return self.async_show_form(
            step_id="discover",
            data_schema=_device_picker_schema(self._discovered),
        )

    async def async_step_discover(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Scan the local subnet for Neewer lights."""
        configured_hosts = await _async_get_configured_hosts(self.hass)

        if user_input is None:
            return await self._async_run_discovery(configured_hosts)

        if "devices" in user_input:
            return await self._async_handle_device_selection(user_input)

        subnet = user_input.get(CONF_SUBNET, "").strip()
        if not subnet:
            return await self._async_run_discovery(configured_hosts)

        try:
            network = parse_ipv4_network(subnet)
        except ValueError:
            _LOGGER.warning("Invalid subnet entered during discovery: %s", subnet)
            return self.async_show_form(
                step_id="discover",
                data_schema=_subnet_retry_schema(),
                errors={"base": "invalid_subnet"},
            )

        local_networks = await async_get_local_networks(self.hass)
        client_ip_override = client_ip_for_network(network, local_networks)
        if client_ip_override is None:
            _LOGGER.warning(
                "No local adapter found for subnet %s (adapters: %s)",
                network,
                [f"{addr}/{net.prefixlen}" for addr, net in local_networks],
            )
            return self.async_show_form(
                step_id="discover",
                data_schema=_subnet_retry_schema(),
                errors={"base": "cannot_determine_client_ip"},
            )

        return await self._async_run_discovery(
            configured_hosts,
            scan_networks=[network],
            client_ip_override=client_ip_override,
        )

    async def _async_handle_device_selection(
        self, user_input: dict[str, Any]
    ) -> FlowResult:
        """Create entries for selected discovered lights."""
        selected_hosts = user_input.get("devices", [])
        if not selected_hosts:
            if not self._discovered:
                return await self.async_step_discover(None)
            return self.async_show_form(
                step_id="discover",
                data_schema=_device_picker_schema(self._discovered),
                errors={"base": "no_devices_selected"},
            )

        devices = [
            self._discovered[host]
            for host in selected_hosts
            if host in self._discovered
        ]
        if not devices:
            return self.async_abort(reason="no_devices_found")

        _LOGGER.info(
            "Adding %d Neewer light(s) from discovery: %s",
            len(devices),
            ", ".join(device.host for device in devices),
        )
        return await self._async_create_device_entries(devices)

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle manual IP entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input.get(CONF_HOST, "").strip()
            if not host:
                errors["base"] = "invalid_host"
            else:
                try:
                    device = await _async_validate_host(self.hass, host)
                except InvalidHost:
                    errors["base"] = "invalid_host"
                except CannotDetermineClientIp:
                    errors["base"] = "cannot_determine_client_ip"
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                else:
                    return await self._async_create_device_entries([device])

        return self.async_show_form(
            step_id="manual",
            data_schema=STEP_MANUAL_SCHEMA,
            errors=errors,
        )

    async def _async_create_device_entries(
        self, devices: list[DiscoveredDevice]
    ) -> FlowResult:
        """Create one config entry per device."""
        pending = [
            device
            for device in devices
            if not self.hass.config_entries.async_entry_for_domain_unique_id(
                DOMAIN, device.unique_id
            )
        ]
        if not pending:
            return self.async_abort(reason="already_configured")

        for device in pending[1:]:
            self.hass.config_entries.async_create_entry(
                DOMAIN,
                title=device.name,
                data=_entry_data(device),
                unique_id=device.unique_id,
            )

        first = pending[0]
        await self.async_set_unique_id(first.unique_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=first.name,
            data=_entry_data(first),
        )


class CannotConnect(HomeAssistantError):
    """Unable to connect to the device."""


class InvalidHost(HomeAssistantError):
    """Invalid host address."""


class CannotDetermineClientIp(HomeAssistantError):
    """Unable to determine local client IP for the subnet."""
