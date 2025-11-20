import json
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import OhMyLightCoordinatorManager

logger = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    logger.debug(f"Oh My Light Installed!, Current config: {json.dumps(config[DOMAIN], ensure_ascii=False)}")

    hass.data.setdefault(DOMAIN, {})
    # 初始化coordinator manager
    hass.data[DOMAIN]["coordinator_manager"] = OhMyLightCoordinatorManager(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    logger.debug(f"<{entry.title}> Setting up entry, Config: {json.dumps(entry.as_dict(), ensure_ascii=False)}")

    coordinator_manager = hass.data[DOMAIN]["coordinator_manager"]
    await coordinator_manager.async_setup_coordinator(entry.title, entry.data["func_name"], entry)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    logger.debug(f"<{entry.title}> Unloading entry, Config: {json.dumps(entry.as_dict(), ensure_ascii=False)}")

    coordinator_manager = hass.data[DOMAIN]["coordinator_manager"]
    await coordinator_manager.async_unload_coordinator(entry.title)
    return True
