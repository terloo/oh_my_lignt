import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry

from .const import DOMAIN

logger = logging.getLogger(__name__)


async def async_parse_light_entity_ids(hass: HomeAssistant, light_entity_ids: list[str]) -> tuple[set[str], set[str]]:
    """
    解析灯实体id列表，将普通灯和灯组id分别放到light_entity_ids和light_group_entity_ids列表中
    """
    light_entity_id_set = set[str]()
    light_group_entity_id_set = set[str]()
    for light_entity_id in light_entity_ids:
        light_entity = hass.states.get(light_entity_id)
        if light_entity is None:
            logger.error(f"Light entity {light_entity_id} not found")
            continue
        if light_entity.attributes.get("entity_id"):
            light_group_entity_id_set.add(light_entity_id)
        else:
            light_entity_id_set.add(light_entity_id)
    return light_entity_id_set, light_group_entity_id_set


async def async_list_light_in_light_group(hass: HomeAssistant, light_group_entity_ids: list[str]) -> set[str]:
    """
    获取灯组中的所有灯实体id
    """
    light_entity_id_set = set[str]()
    for light_group_entity_id in light_group_entity_ids:
        light_group_entity = hass.states.get(light_group_entity_id)
        if light_group_entity is None:
            logger.error(f"Light group entity {light_group_entity_id} not found")
            continue
        light_entity_ids = light_group_entity.attributes.get("entity_id")
        if light_entity_ids:
            light_entity_id_set.update(light_entity_ids)
    return light_entity_id_set


async def async_list_light_sync_entry(
    hass: HomeAssistant, domain: str = DOMAIN, func_name: str = None
) -> list[ConfigEntry]:
    """
    获取所有sync_light config entry
    """

    if func_name is None:
        return []

    config_entries = hass.config_entries.async_entries(domain)
    return [config_entry for config_entry in config_entries if config_entry.data["func_name"] == func_name]


async def _async_list_switch_event_entity_ids(hass: HomeAssistant, switch_entity_id: str = None) -> list[str]:
    """
    通过开关实体id获取开关所有的event entity id列表
    """
    if switch_entity_id is None:
        return None
    ent_reg = entity_registry.async_get(hass)
    entity_entry = ent_reg.async_get(switch_entity_id)
    if entity_entry is None:
        logger.error(f"Switch entity {switch_entity_id} not found")
        return None

    event_entity_ids = []
    for ent in entity_registry.async_entries_for_device(ent_reg, entity_entry.device_id):
        if ent.entity_id.startswith("event."):
            event_entity_ids.append(ent.entity_id)
    return event_entity_ids
