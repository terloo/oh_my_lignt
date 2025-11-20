import datetime
import logging
from abc import ABC, abstractmethod

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import FUNC_NAME_LIGHT_EVENT_BIND, FUNC_NAME_LIGHT_SWITCH_BIND, FUNC_NAME_LIGHT_SYNC
from .utils import _async_list_switch_event_entity_ids

logger = logging.getLogger(__name__)

LIGHT_SERVICES = {
    STATE_ON: "turn_on",
    STATE_OFF: "turn_off",
}

SWITCH_SERVICES = {
    STATE_ON: "turn_on",
    STATE_OFF: "turn_off",
}


class BaseCoordinator(ABC):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass: HomeAssistant = hass
        self.config_entry: ConfigEntry = entry
        self.func_name: str = self.config_entry.data["func_name"]
        self.func_data: dict = self.config_entry.data["func_data"]
        self._unsub_callbacks: list[callable] = []
        # 被扇出的实体id，用于避免循环更新
        self._fanned_out_entity_ids: set[str] = set[str]()
        self._last_update_timestamp = 0
        # 缓存灯组中的所有灯实体
        self._lights_of_group: dict[str, list[str]] = {}
        self._lights_in_group: list[str] = []

    @abstractmethod
    async def async_list_entities_to_listen(self) -> set[str]:
        """返回需要监听状态变化的实体id列表"""
        raise NotImplementedError

    @abstractmethod
    async def async_handle_event(self, event: Event):
        """处理实体状态变化事件"""
        raise NotImplementedError

    async def async_setup(self):
        logger.debug(f"<{self.config_entry.title}> Setting up coordinator")
        # 获取需要监听状态变化的实体id列表
        entity_ids = await self.async_list_entities_to_listen()
        logger.debug(f"<{self.config_entry.title}> Coordinator will listen entity ids: {entity_ids}")

        if not entity_ids:
            logger.warning(f"<{self.config_entry.title}> No entity ids to listen")
            return

        @callback
        async def handle_event(event: Event) -> None:
            logger.debug(f"<{self.config_entry.title}> {self.func_name} event: {event.as_dict()}")
            await self.async_handle_event(event)

        # 发起监听实体状态变化事件
        unsub_callback = async_track_state_change_event(
            self.hass,
            entity_ids,
            handle_event,
        )
        self._unsub_callbacks.append(unsub_callback)
        logger.debug(f"<{self.config_entry.title}> Listening entity ids: {entity_ids}")

    async def async_unload(self):
        logger.debug(f"<{self.config_entry.title}> Unloading coordinator")
        for unsub_callback in self._unsub_callbacks:
            unsub_callback()
        self._unsub_callbacks.clear()

    async def _async_set_light_entity_state(
        self,
        entity_id: str,
        desired_state: str,
        desired_attributes: dict = None,
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

    async def _async_refresh_lights_in_group(self):
        """刷新灯组中的所有灯实体"""
        logger.debug(f"<{self.config_entry.title}> Refreshing lights in group")
        self._lights_of_group.clear()
        self._lights_in_group.clear()

        func_data = self.func_data
        for light_group_entity_id in func_data["light_group_entity_ids"]:
            light_state = self.hass.states.get(light_group_entity_id)
            if not light_state:
                logger.error(f"Light group entity {light_group_entity_id} not found")
                continue
            light_attribute_entity_id = light_state.attributes.get("entity_id")
            if light_attribute_entity_id:
                self._lights_of_group[light_group_entity_id] = light_attribute_entity_id
                self._lights_in_group.extend(light_attribute_entity_id)
            else:
                self._lights_of_group[light_group_entity_id] = []
        self._lights_in_group = list(set(self._lights_in_group))
        logger.debug(
            f"<{self.config_entry.title}> Refresh done. lights in group: {self._lights_in_group}, light of groups: {self._lights_of_group}"
        )


class LightSyncCoordinator(BaseCoordinator):
    """灯同步协调器"""

    async def async_list_entities_to_listen(self) -> set[str]:
        """返回需要监听状态变化的实体id列表"""
        light_entity_ids = self.func_data["light_entity_ids"]
        light_group_entity_ids = self.func_data["light_group_entity_ids"]
        if not light_entity_ids and not light_group_entity_ids:
            logger.error(f"No any light entity ids found in entry {self.config_entry.title}")
            return
        await self._async_refresh_lights_in_group()
        return set(light_entity_ids + light_group_entity_ids + self._lights_in_group)

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

        # 如果上次更新时间距离现在大于一定时间，清空被扇出的实体id
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
        logger.debug(f"{entity_id=}")

        # 将所有其他的灯实体放到扇出队列中，包括灯组和灯组中的所有灯实体
        self._fanned_out_entity_ids.update(
            [
                e
                for e in (
                    self.func_data["light_entity_ids"]
                    + self.func_data["light_group_entity_ids"]
                    + self._lights_in_group
                )
                if e != entity_id
            ]
        )

        # 将需要变更的实体添加到需要更新的实体id队列中
        need_update_entity_ids = set[str](self.func_data["light_entity_ids"])
        for light_group_entity_id, light_ids in self._lights_of_group.items():
            if light_group_entity_id == entity_id:
                # 如果灯组是发生了变更，则忽略灯组下所有的灯实体
                continue
            need_update_entity_ids.update(light_ids)
        if entity_id in need_update_entity_ids:
            need_update_entity_ids.remove(entity_id)

        # 修改所有灯光状态
        for light_entity_id in need_update_entity_ids:
            await self._async_set_light_entity_state(light_entity_id, state, new_state.attributes)

        self._last_update_timestamp = event.time_fired


class LightSwitchBindCoordinator(BaseCoordinator):
    """灯开关绑定协调器"""

    async def async_list_entities_to_listen(self) -> set[str]:
        """返回需要监听状态变化的实体id列表"""
        light_entity_ids = self.func_data["light_entity_ids"]
        switch_entity_ids = self.func_data["switch_entity_ids"]
        is_wireless = self.func_data["is_wireless"]
        if is_wireless:
            # 不监听开关实体，而是监听开关事件
            switch_event_ids = [
                switch_event_id
                for switch_entity_id in switch_entity_ids
                if switch_entity_id
                for switch_event_id in await _async_list_switch_event_entity_ids(self.hass, switch_entity_id)
                if switch_event_id
            ]
            self.func_data["switch_event_ids"] = switch_event_ids
            listen_entities = set(light_entity_ids + switch_event_ids)
        else:
            listen_entities = set(light_entity_ids + switch_entity_ids)
        return listen_entities

    async def async_handle_event(self, event: Event):
        """处理实体状态变化事件"""
        light_entity_ids = self.func_data["light_entity_ids"]
        switch_entity_ids = self.func_data["switch_entity_ids"]
        switch_event_ids = self.func_data["switch_event_ids"]
        is_wireless = self.func_data["is_wireless"]

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

        # 如果上次更新时间距离现在大于1秒，清空被扇出的实体id
        if not self._last_update_timestamp or event.time_fired - self._last_update_timestamp > datetime.timedelta(
            seconds=3
        ):
            logger.debug("Clear fanned out entity ids")
            self._fanned_out_entity_ids.clear()

        if entity_id in switch_entity_ids:
            if is_wireless:
                # 无线开关发生了状态变更，忽略
                logger.debug(f"Wireless switch entity {entity_id} state change, ignore")
                return
            # 修改所有灯光状态
            for light_entity_id in light_entity_ids:
                await self._async_set_light_entity_state(light_entity_id, new_state.state, new_state.attributes)
            self._fanned_out_entity_ids.update(light_entity_ids)
            logger.debug(f"Set light entity {light_entity_id} state to {new_state.state}")
            return
        elif entity_id in light_entity_ids:
            if is_wireless:
                # 无线开关，灯实体发生了状态变更，忽略
                logger.debug(f"Light of wireless entity {entity_id} state change, ignore")
                return
            # 修改开关状态
            for switch_entity_id in switch_entity_ids:
                await self._async_set_switch_entity_state(
                    switch_entity_id, new_state.state, new_state.attributes, event.context
                )
            self._fanned_out_entity_ids.update(switch_entity_ids)
            logger.debug(f"Set switch entity {switch_entity_id} state to {new_state.state}")
            return
        elif entity_id in switch_event_ids:
            # 触发了开关单击事件，反转灯开关状态
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
            self._fanned_out_entity_ids.update(light_entity_ids)
            logger.debug(
                f"Set light entity {light_entity_id} state to {STATE_OFF if light_state.state == STATE_ON else STATE_ON}"
            )
            return

        logger.error(f"Unknown entity id {entity_id} in entry {self.config_entry.title}")
        return


class LightEventBindCoordinator(BaseCoordinator):
    """灯事件绑定协调器"""

    async def async_list_entities_to_listen(self) -> set[str]:
        """返回需要监听状态变化的实体id列表"""
        pass

    @callback
    async def async_handle_event(self, event: Event):
        """处理实体状态变化事件"""
        pass


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
        if entry_titile not in self.coordinators:
            if func_name not in self.coordinator_types:
                logger.error(f"Unknown coordinator type: {func_name}")
                return None
            self.coordinators[entry_titile] = self.coordinator_types[func_name](self.hass, config_entry)
            await self.coordinators[entry_titile].async_setup()
        return self.coordinators[entry_titile]

    async def async_unload_coordinator(self, entry_titile: str) -> None:
        """卸载协调器"""
        if entry_titile in self.coordinators:
            await self.coordinators[entry_titile].async_unload()
            del self.coordinators[entry_titile]
