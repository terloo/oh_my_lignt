import logging
import json

from .const import DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import ConfigType
from homeassistant.core import HomeAssistant
from .coordinator import OhMyLightCoordinator

logger = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    logger.debug(
        f"Oh My Light Installed!, Current config: {json.dumps(config[DOMAIN], ensure_ascii=False)}"
    )

    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    logger.debug(
        f"Setting up Oh My Light entry: <{entry.title}>, Detail: {json.dumps(entry.as_dict(), ensure_ascii=False)}"
    )

    coordinator = OhMyLightCoordinator(hass, entry)
    await coordinator.async_setup()
    hass.data[DOMAIN][entry.unique_id] = coordinator
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    logger.debug(
        f"Unloading Oh My Light entry: <{entry.title}>, Detail: {json.dumps(entry.as_dict(), ensure_ascii=False)}"
    )

    coordinator = hass.data[DOMAIN].pop(entry.unique_id)
    await coordinator.async_unload()
    return True
