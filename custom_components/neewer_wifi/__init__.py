"""The Neewer WiFi integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN, PLATFORMS
from .coordinator import NeewerHub

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Neewer WiFi component."""
    hass.data.setdefault(DOMAIN, NeewerHub(hass))
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Neewer WiFi from a config entry."""
    hub: NeewerHub = hass.data[DOMAIN]

    if not hub.coordinators:
        try:
            await hub.async_setup()
        except OSError as err:
            raise ConfigEntryNotReady(f"Failed to bind UDP port: {err}") from err

    try:
        await hub.async_register_entry(entry)
    except OSError as err:
        raise ConfigEntryNotReady(f"Failed to connect to {entry.data['host']}: {err}") from err

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    hub: NeewerHub = hass.data[DOMAIN]
    await hub.async_unregister_entry(entry)

    if not hub.coordinators:
        await hub.async_shutdown()

    return unload_ok
