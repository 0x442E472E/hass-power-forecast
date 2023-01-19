"""The Power Forecast integration."""
from __future__ import annotations


from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN


PLATFORMS: list[Platform] = [Platform.SENSOR]

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Power Forecast component from yaml configuration."""
    hass.data.setdefault(DOMAIN, {})
    return True


