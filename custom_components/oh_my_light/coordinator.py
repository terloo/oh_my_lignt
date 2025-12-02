import datetime
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import FUNC_NAME_LIGHT_EVENT_BIND, FUNC_NAME_LIGHT_SWITCH_BIND, FUNC_NAME_LIGHT_SYNC
from .utils import async_parse_light, async_whether_light_listen_by_other

logger = logging.getLogger(__name__)

LIGHT_SERVICES = {
    STATE_ON: "turn_on",
    STATE_OFF: "turn_off",
}

SWITCH_SERVICES = {
    STATE_ON: "turn_on",
    STATE_OFF: "turn_off",
}


@dataclass
class ListenResult:
    """实体监听结果"""

    entity_ids: set[str]  # 需要监听的实体ID列表
    satisfied: bool = False  # 是否满足监听条件
    unsatisfied_reason: str | None = None  # 不满足监听条件的原因
    unsatisfied_reason_placeholders: dict | None = None  # 不满足监听条件的原因占位符


class BaseCoordinator(ABC):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass: HomeAssistant = hass
        self.config_entry: ConfigEntry = entry
        setattr(self.config_entry, "coordinator", self)
        self.func_name: str = self.config_entry.data["func_name"]
        self.func_data: dict = self.config_entry.data["func_data"]
        self._unsub_callbacks: list[callable] = []
        # 被扇出的实体id，用于避免循环更新
        self._fanned_out_entity_ids: set[str] = set[str]()
        self._last_update_timestamp = 0
        # 缓存本Coordinator监听的所有灯实体id
        self._listened_entity_ids: set[str] = set[str]()
        self._lights_of_group: dict[str, set[str]] = {}
        self._lights_in_group: set[str] = set[str]()

    @abstractmethod
    async def async_list_entities_to_listen(self) -> ListenResult:
        """返回需要监听状态变化的实体id列表"""
        raise NotImplementedError

    @abstractmethod
    async def async_handle_event(self, event: Event):
        """处理实体状态变化事件"""
        raise NotImplementedError

    async def async_setup(self):
        logger.debug(f"<{self.config_entry.title}> Setting up coordinator")
        # 获取需要监听状态变化的实体id列表
        listener_result = await self.async_list_entities_to_listen()
        if not listener_result.satisfied:
            logger.warning(
                f"<{self.config_entry.title}> No entity ids to listen, reason: {listener_result.unsatisfied_reason}"
            )
            # 禁用该entry的监听功能
            await self.async_unload()
            self.config_entry._async_set_state(
                hass=self.hass,
                state=ConfigEntryState.SETUP_ERROR,
                reason=listener_result.unsatisfied_reason,
                error_reason_translation_key=listener_result.unsatisfied_reason,
                error_reason_translation_placeholders=listener_result.unsatisfied_reason_placeholders,
            )
            return

        logger.debug(f"<{self.config_entry.title}> Coordinator will listen entity ids: {listener_result.entity_ids}")

        @callback
        async def handle_event(event: Event) -> None:
            logger.debug(f"<{self.config_entry.title}> {self.func_name} event: {event.as_dict()}")
            await self.async_handle_event(event)

        # 发起监听实体状态变化事件
        unsub_callback = async_track_state_change_event(
            self.hass,
            listener_result.entity_ids,
            handle_event,
        )
        self._unsub_callbacks.append(unsub_callback)
        logger.debug(f"<{self.config_entry.title}> Listening entity ids: {listener_result.entity_ids}")
        self._listened_entity_ids = listener_result.entity_ids

    async def async_unload(self):
        logger.debug(f"<{self.config_entry.title}> Unloading coordinator")
        for unsub_callback in self._unsub_callbacks:
            unsub_callback()
        self._unsub_callbacks.clear()

    async def _async_set_light_entity_state(
        self,
        entity_id: str,
        desired_state: str,
        desired_attributes: dict = {},
    ) -> None:
        logger.debug(f"Setting entity {entity_id} to state {desired_state} with attributes {desired_attributes}")
        domain = entity_id.split(".")[0]
        if domain != "light":
            logger.error(f"Entity {entity_id} is not a light entity")
            return

        # 校验desired_state是否为on或off
        if desired_state not in [STATE_ON, STATE_OFF]:
            logger.error(f"Invalid desired state {desired_state}")
            return

        # 处理desired_attributes
        if desired_state == STATE_OFF:
            desired_attributes = {}
        if desired_attributes:
            desired_attributes = {
                k: v
                for k, v in desired_attributes.items()
                if k
                in [
                    "brightness",
                    "color_temp_kelvin",
                ]
                and v is not None
            }

        try:
            # 调用Home Assistant服务来设置实体状态
            await self.hass.services.async_call(
                domain,
                LIGHT_SERVICES[desired_state],
                {**{"entity_id": entity_id, **desired_attributes}},
            )
            logger.info(f"Successfully set {entity_id} to state {desired_state} with attributes {desired_attributes}")
        except Exception:
            logger.error(
                f"Failed to set {entity_id} to state {desired_state} with attributes {desired_attributes}",
                exc_info=True,
            )

    async def _async_set_switch_entity_state(
        self,
        entity_id: str,
        desired_state: str,
    ) -> None:
        logger.debug(f"Setting switch {entity_id} to state {desired_state} ")
        domain = entity_id.split(".")[0]

        if domain != "switch":
            logger.error(f"Entity {entity_id} is not a switch entity")
            return

        # 校验desired_state是否为on或off
        if desired_state not in [STATE_ON, STATE_OFF]:
            logger.error(f"Invalid desired state {desired_state}")
            return

        try:
            # 调用Home Assistant服务来设置实体状态
            await self.hass.services.async_call(
                domain,
                SWITCH_SERVICES[desired_state],
                {"entity_id": entity_id},
            )
            logger.info(f"Successfully set {entity_id} to state {desired_state}")
        except Exception:
            logger.error(
                f"Failed to set {entity_id} to state {desired_state}",
                exc_info=True,
            )


class LightSyncCoordinator(BaseCoordinator):
    """灯同步协调器"""

    async def async_list_entities_to_listen(self) -> ListenResult:
        """返回需要监听状态变化的实体id列表"""
        light_sync_entity_ids = self.func_data["light_sync_entity_ids"]
        if not light_sync_entity_ids:
            logger.error(f"No any light sync entity ids found in entry {self.config_entry.title}")
            return ListenResult(
                satisfied=False,
                entity_ids=set(light_sync_entity_ids),
                errors={
                    "light_sync_entity_ids": f"No any light sync entity ids found in entry {self.config_entry.title}"
                },
            )

        # 判断是否有灯实体id在其他配置项中被监听，如果有监听则提示并让用户修改输入
        (
            normal_light_entity_ids,
            light_of_group_entity_ids,
        ) = await async_parse_light(self.hass, light_sync_entity_ids)

        (
            existing_light_entity_ids,
            existing_config_entry,
        ) = await async_whether_light_listen_by_other(
            self.hass,
            self.config_entry.title,
            self.func_name,
            normal_light_entity_ids.union(*light_of_group_entity_ids.values()),
        )
        if existing_light_entity_ids:
            logger.error(
                f"<{self.config_entry.title}> Light entity ids {existing_light_entity_ids} are listened by entry {existing_config_entry.title}"
            )
            return ListenResult(
                satisfied=False,
                entity_ids=None,
                unsatisfied_reason="light_entity_ids_in_other_entries",
                unsatisfied_reason_placeholders={
                    "existing_light_entity_ids": ",".join(existing_light_entity_ids),
                    "existing_config_entry_id": existing_config_entry.title,
                },
            )
        self._lights_in_group = set[str]().union(*light_of_group_entity_ids.values())
        self._lights_of_group = light_of_group_entity_ids
        return ListenResult(
            satisfied=True,
            entity_ids=normal_light_entity_ids.union(
                light_of_group_entity_ids.keys(), *light_of_group_entity_ids.values()
            ),
        )

    async def async_handle_event(self, event: Event):
        """处理实体状态变化事件"""

        old_state = event.data.get("old_state")
        if not old_state:
            logger.debug("No old state found, skip")
            return

        entity_id = event.data.get("entity_id")
        if not entity_id:
            logger.error("No entity id found in event data")
            return

        new_state = event.data.get("new_state")
        if not new_state:
            logger.error("No new state found in event data")
            return

        state = new_state.state
        if not state:
            logger.error("No state found in new state")
            return

        # 如果变更entity是灯组且old_state是unavailable，则说明灯组的灯发生了变更，重新监听灯组中的所有灯实体
        if entity_id in self._lights_of_group and old_state.state == STATE_UNAVAILABLE:
            logger.debug(f"Light group entity {entity_id} old state is unavailable, refresh and listen lights in group")
            await self.async_unload()
            await self.async_setup()
            return

        # 如果new_state不是on或者off，可能是灯离线了，直接返回不做处理
        if state not in [STATE_ON, STATE_OFF]:
            logger.debug(f"Ingore this event, state <{state}> is not in {[STATE_ON, STATE_OFF]}")
            return

        # 清空被扇出的实体id
        if not self._last_update_timestamp or event.time_fired - self._last_update_timestamp > datetime.timedelta(
            seconds=3
        ):
            logger.debug("Clear fanned out entity ids")
            self._fanned_out_entity_ids.clear()

        # 如果变更的entity_id在被扇出的实体id中，直接返回不做处理
        entity_id = event.data.get("entity_id")
        if entity_id in self._fanned_out_entity_ids:
            logger.debug(f"<{self.config_entry.title}> Ingore this event, entity {entity_id} is fanned out")
            return

        # 将所有其他的灯实体放到扇出队列中，包括灯组和灯组中的所有灯实体
        self._fanned_out_entity_ids.update(
            [
                e
                for e in (
                    set(self.func_data["light_sync_entity_ids"])
                    .union(self._lights_of_group.keys())
                    .union(self._lights_in_group)
                )
                if e != entity_id
            ]
        )

        # 将需要变更的实体添加到需要更新的实体id队列中
        need_update_entity_ids = set[str](self.func_data["light_sync_entity_ids"])
        if entity_id in need_update_entity_ids:
            need_update_entity_ids.remove(entity_id)

        # 修改所有灯光状态
        for light_entity_id in need_update_entity_ids:
            await self._async_set_light_entity_state(light_entity_id, state, new_state.attributes)

        self._last_update_timestamp = event.time_fired


class LightSwitchBindCoordinator(BaseCoordinator):
    """灯开关绑定协调器"""

    async def async_list_entities_to_listen(self) -> ListenResult:
        """返回需要监听状态变化的实体id列表"""
        light_entity_ids = self.func_data["light_entity_ids"]
        switch_entity_ids = self.func_data["switch_entity_ids"]
        return ListenResult(
            satisfied=True,
            entity_ids=set(light_entity_ids + switch_entity_ids),
        )

    async def async_handle_event(self, event: Event):
        """处理实体状态变化事件"""
        light_entity_ids = self.func_data["light_entity_ids"]
        switch_entity_ids = self.func_data["switch_entity_ids"]

        old_state = event.data.get("old_state")
        if not old_state:
            logger.debug("No old state found, skip")
            return

        entity_id = event.data.get("entity_id")
        if not entity_id:
            logger.error("No entity id found in event data")
            return

        new_state = event.data.get("new_state")
        if not new_state:
            logger.error("No new state found in event data")
            return

        # 清空被扇出的实体id
        if not self._last_update_timestamp or event.time_fired - self._last_update_timestamp > datetime.timedelta(
            seconds=3
        ):
            logger.debug("Clear fanned out entity ids")
            self._fanned_out_entity_ids.clear()

        if entity_id not in light_entity_ids + switch_entity_ids:
            logger.error(f"Unknown entity id {entity_id} in entry {self.config_entry.title}")
            return

        need_update_entity_ids = set[str](light_entity_ids + switch_entity_ids)
        self._fanned_out_entity_ids.update(light_entity_ids)
        if entity_id in need_update_entity_ids:
            need_update_entity_ids.remove(entity_id)
        # 修改所有灯光和开关状态
        for entity_id in need_update_entity_ids:
            if entity_id in light_entity_ids:
                await self._async_set_light_entity_state(entity_id, new_state.state)
                logger.debug(f"Set light entity {entity_id} state to {new_state.state}")
            elif entity_id in switch_entity_ids:
                await self._async_set_switch_entity_state(entity_id, new_state.state)
                logger.debug(f"Set switch entity {entity_id} state to {new_state.state}")

        self._last_update_timestamp = event.time_fired


class LightEventBindCoordinator(BaseCoordinator):
    """灯事件绑定协调器"""

    async def async_list_entities_to_listen(self) -> ListenResult:
        """返回需要监听状态变化的实体id列表"""
        event_entity_ids = self.func_data["event_entity_ids"]
        return ListenResult(
            satisfied=True,
            entity_ids=set(event_entity_ids),
        )

    async def async_handle_event(self, event: Event):
        """处理实体状态变化事件"""
        light_entity_ids = self.func_data["light_entity_ids"]
        event_entity_ids = self.func_data["event_entity_ids"]

        old_state = event.data.get("old_state")
        if not old_state:
            logger.debug("No old state found, skip")
            return

        entity_id = event.data.get("entity_id")
        if not entity_id:
            logger.error("No entity id found in event data")
            return

        new_state = event.data.get("new_state")
        if not new_state:
            logger.error("No new state found in event data")
            return

        # 清空被扇出的实体id
        if not self._last_update_timestamp or event.time_fired - self._last_update_timestamp > datetime.timedelta(
            seconds=3
        ):
            logger.debug("Clear fanned out entity ids")
            self._fanned_out_entity_ids.clear()

        if entity_id not in event_entity_ids:
            logger.error(f"Unknown entity id {entity_id} in entry {self.config_entry.title}")
            return

        # 触发了开关单击事件，反转灯开关状态
        self._fanned_out_entity_ids.update(light_entity_ids)
        for light_entity_id in light_entity_ids:
            light_state = self.hass.states.get(light_entity_id)
            if not light_state:
                logger.error(f"Light entity {light_entity_id} not found")
                continue
            await self._async_set_light_entity_state(
                light_entity_id,
                STATE_OFF if light_state.state == STATE_ON else STATE_ON,
                {},
            )
        logger.debug(
            f"Set light entity {light_entity_id} state to {STATE_OFF if light_state.state == STATE_ON else STATE_ON}"
        )

        self._last_update_timestamp = event.time_fired


class OhMyLightCoordinatorManager:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass: HomeAssistant = hass
        self.coordinators: dict[str, BaseCoordinator] = {}
        self.coordinator_types: map[str, type[BaseCoordinator]] = {
            FUNC_NAME_LIGHT_SYNC: LightSyncCoordinator,
            FUNC_NAME_LIGHT_SWITCH_BIND: LightSwitchBindCoordinator,
            FUNC_NAME_LIGHT_EVENT_BIND: LightEventBindCoordinator,
        }

    async def async_setup_coordinator(
        self, entry_titile: str, func_name: str, config_entry: ConfigEntry
    ) -> BaseCoordinator | None:
        """根据协调器类型设置协调器实例"""
        if func_name not in self.coordinator_types:
            logger.error(f"Unknown coordinator type: {func_name}")
            return None
        if entry_titile in self.coordinators:
            logger.debug(f"Coordinator {entry_titile} already setup, return existing coordinator")
            await self.async_unload_coordinator(entry_titile)

        logger.debug(f"Setting up coordinator {entry_titile} with type {func_name}")
        self.coordinators[entry_titile] = self.coordinator_types[func_name](self.hass, config_entry)
        await self.coordinators[entry_titile].async_setup()
        return self.coordinators[entry_titile]

    async def async_unload_coordinator(self, entry_titile: str) -> None:
        """卸载协调器"""
        logger.debug(f"Unloading coordinator {entry_titile}")
        if entry_titile in self.coordinators:
            await self.coordinators[entry_titile].async_unload()
            del self.coordinators[entry_titile]
