"""Light platform for Neewer WiFi."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_HOST,
    DEFAULT_MODEL,
    DOMAIN,
    MAX_COLOR_TEMP_KELVIN,
    MIN_COLOR_TEMP_KELVIN,
)
from .coordinator import NeewerDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Neewer WiFi lights from a config entry."""
    hub = hass.data[DOMAIN]
    coordinator = hub.get_coordinator(entry)
    if coordinator is None:
        raise RuntimeError(f"Coordinator missing for entry {entry.entry_id}")

    async_add_entities([NeewerWifiLight(coordinator, entry)])
    _LOGGER.info("Added light entity for %s", entry.data[CONF_HOST])


class NeewerWifiLight(CoordinatorEntity[NeewerDataUpdateCoordinator], LightEntity):
    """Representation of a Neewer WiFi light."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_color_modes = {ColorMode.COLOR_TEMP}
    _attr_min_color_temp_kelvin = MIN_COLOR_TEMP_KELVIN
    _attr_max_color_temp_kelvin = MAX_COLOR_TEMP_KELVIN

    def __init__(
        self,
        coordinator: NeewerDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        host = entry.data[CONF_HOST]
        host_suffix = host.rsplit(".", 1)[-1]
        self._attr_unique_id = entry.unique_id
        self._attr_suggested_object_id = f"neewer_gl1_pro_{host_suffix}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.unique_id)},
            "name": entry.title,
            "manufacturer": "Neewer",
            "model": DEFAULT_MODEL,
        }

    @property
    def is_on(self) -> bool:
        """Return true if the light is on."""
        return self.coordinator.state.is_on

    @property
    def brightness(self) -> int | None:
        """Return the brightness of the light."""
        if not self.is_on:
            return None
        return self.coordinator.state.brightness

    @property
    def color_temp_kelvin(self) -> int | None:
        """Return the color temperature in kelvin."""
        if not self.is_on:
            return None
        return self.coordinator.state.color_temp_kelvin

    @property
    def color_mode(self) -> ColorMode | None:
        """Return the color mode."""
        if not self.is_on:
            return None
        return ColorMode.COLOR_TEMP

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        color_temp_kelvin = kwargs.get(ATTR_COLOR_TEMP_KELVIN)
        await self.coordinator.async_turn_on(
            brightness=brightness,
            color_temp_kelvin=color_temp_kelvin,
        )
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self.coordinator.async_turn_off()
        self.async_write_ha_state()
