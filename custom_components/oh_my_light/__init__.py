import json
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import OhMyLightCoordinator

logger = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    logger.debug(f"Oh My Light Installed!, Current config: {json.dumps(config[DOMAIN], ensure_ascii=False)}")

    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    logger.debug(f"<{entry.title}> Setting up entry, Detail: {json.dumps(entry.as_dict(), ensure_ascii=False)}")

    coordinator = OhMyLightCoordinator(hass, entry)
    await coordinator.async_setup()
    hass.data[DOMAIN][entry.unique_id] = coordinator
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    logger.debug(f"<{entry.title}> Unloading entry, Detail: {json.dumps(entry.as_dict(), ensure_ascii=False)}")

    coordinator = hass.data[DOMAIN].pop(entry.unique_id)
    await coordinator.async_unload()
    return True
