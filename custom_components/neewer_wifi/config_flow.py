"""Config flow for Neewer WiFi."""

from __future__ import annotations

import ipaddress
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

from .const import CONF_CLIENT_IP, DOMAIN
from .discovery import (
    async_discover_neewer_lights,
    async_get_local_networks,
    client_ip_for_host,
    DiscoveredDevice,
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
    try:
        ipaddress.ip_address(host)
    except ValueError as err:
        raise InvalidHost from err

    networks = await async_get_local_networks(hass)
    client_ip = client_ip_for_host(host, networks)
    if client_ip is None:
        raise CannotDetermineClientIp

    if not await async_probe_light(host, client_ip):
        raise CannotConnect

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

    async def async_step_discover(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Scan the local subnet for Neewer lights."""
        configured_hosts = await _async_get_configured_hosts(self.hass)

        if user_input is None:
            self._discovered = {}
            discovered = await async_discover_neewer_lights(
                self.hass,
                exclude_hosts=configured_hosts,
            )
            for device in discovered:
                self._discovered[device.host] = device

            if not self._discovered:
                return self.async_show_form(
                    step_id="discover",
                    data_schema=vol.Schema({}),
                    errors={"base": "no_devices_found"},
                    description_placeholders={},
                )

            options = [
                selector.SelectOptionDict(value=host, label=device.name)
                for host, device in self._discovered.items()
            ]
            schema = vol.Schema(
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
            return self.async_show_form(step_id="discover", data_schema=schema)

        selected_hosts = user_input["devices"]
        if not selected_hosts:
            options = [
                selector.SelectOptionDict(value=host, label=device.name)
                for host, device in self._discovered.items()
            ]
            schema = vol.Schema(
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
            return self.async_show_form(
                step_id="discover",
                data_schema=schema,
                errors={"base": "no_devices_selected"},
            )

        devices = [
            self._discovered[host]
            for host in selected_hosts
            if host in self._discovered
        ]
        if not devices:
            return self.async_abort(reason="no_devices_found")

        return await self._async_create_device_entries(devices)

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle manual IP entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
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

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> NeewerWifiOptionsFlow:
        """Return the options flow handler."""
        return NeewerWifiOptionsFlow(config_entry)


class NeewerWifiOptionsFlow(config_entries.OptionsFlow):
    """Handle Neewer WiFi options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage options."""
        if user_input is not None:
            client_ip = user_input.get(CONF_CLIENT_IP, "").strip()
            data = self.config_entry.data.copy()
            if client_ip:
                data[CONF_CLIENT_IP] = client_ip
            self.hass.config_entries.async_update_entry(self.config_entry, data=data)
            return self.async_create_entry(title="", data={})

        current_client_ip = self.config_entry.data.get(CONF_CLIENT_IP, "")
        schema = vol.Schema(
            {
                vol.Optional(CONF_CLIENT_IP, default=current_client_ip): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


class CannotConnect(HomeAssistantError):
    """Unable to connect to the device."""


class InvalidHost(HomeAssistantError):
    """Invalid host address."""


class CannotDetermineClientIp(HomeAssistantError):
    """Unable to determine local client IP for the subnet."""
