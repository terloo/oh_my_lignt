import logging

from homeassistant.components.group.light import LightGroup
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_component import EntityComponent

from .const import DOMAIN

logger = logging.getLogger(__name__)


async def is_light_group_entity(hass: HomeAssistant, entity_id: str) -> bool:
    """
    判断一个entity_id是否是灯组
    """
    if not entity_id:
        return False
    if not entity_id.startswith("light."):
        return False
    entity_component: EntityComponent = hass.data.get("entity_components", {}).get("light")
    light_entity = entity_component.get_entity(entity_id)
    if light_entity is None:
        logger.error(f"Light entity {entity_id} not found")
        return False
    return isinstance(light_entity, LightGroup)


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


async def async_parse_light(hass: HomeAssistant, light_entity_ids: list[str]) -> tuple[set[str], dict[str, set[str]]]:
    """
    解析灯实体列表，返回普通灯和灯组及灯中包含的普通灯
    """
    normal_light_entity_ids = set[str]()
    light_of_group_entity_ids = dict[str, set[str]]()
    for light_entity_id in light_entity_ids:
        light_entity = hass.states.get(light_entity_id)
        if light_entity is None:
            logger.error(f"Light entity {light_entity_id} not found")
            continue
        if await is_light_group_entity(hass, light_entity_id):
            light_of_group_entity_ids[light_entity_id] = await async_list_light_in_light_group(hass, [light_entity_id])
        else:
            normal_light_entity_ids.add(light_entity_id)
    return normal_light_entity_ids, light_of_group_entity_ids


async def async_list_light_sync_entry(
    hass: HomeAssistant, domain: str = DOMAIN, func_name: str = None
) -> list[ConfigEntry]:
    """
    获取指定func_name的所有config entry
    """

    if func_name is None:
        return []

    config_entries = hass.config_entries.async_entries(domain)
    return [config_entry for config_entry in config_entries if config_entry.data["func_name"] == func_name]


async def async_whether_light_listen_by_other(
    hass: HomeAssistant, entry_name: str, func_name: str, light_entity_ids_set: set[str]
) -> tuple[set[str], ConfigEntry | None]:
    """
    检查light_entity_ids_set中的灯实体id是否在其他配置项中被监听，返回被使用了的灯实体和灯组实体id
    """

    for config_entry in await async_list_light_sync_entry(hass, func_name=func_name):
        if config_entry.title == entry_name:
            continue
        if not hasattr(config_entry, "coordinator"):
            continue
        coordinator = config_entry.coordinator
        if not hasattr(coordinator, "_listened_entity_ids"):
            logger.warning(f"Coordinator {coordinator} has no listened_entity_ids")
            continue
        listened_entity_ids = coordinator._listened_entity_ids
        if existing_light_entity_ids := light_entity_ids_set.intersection(listened_entity_ids):
            return existing_light_entity_ids, config_entry
    return set(), None
