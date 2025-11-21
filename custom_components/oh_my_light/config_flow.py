import logging
from abc import ABC, abstractmethod
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import DOMAIN, FUNC_NAME_LIGHT_EVENT_BIND, FUNC_NAME_LIGHT_SWITCH_BIND, FUNC_NAME_LIGHT_SYNC
from .utils import (
    async_list_light_in_light_group,
    async_list_light_sync_entry,
    async_parse_light_entity_ids,
)

logger = logging.getLogger(__name__)


class UserInputParseResult:
    """
    包装user_input的解析结果
    """

    def __init__(
        self,
        create_entry: bool,
        data_or_schema: dict[str, Any],
        errors: dict[str, str],
        description_placeholders: dict[str, str] = None,
    ) -> None:
        self.create_entry = create_entry
        self.data_or_schema = data_or_schema
        self.errors = errors
        self.description_placeholders = description_placeholders or {}

    def as_dict(self) -> dict[str, Any]:
        return {
            "create_entry": self.create_entry,
            "data_or_schema": self.data_or_schema,
            "errors": self.errors,
            "description_placeholders": self.description_placeholders,
        }


class OhMyLightBaseFlowManager(ABC):
    """
    基础类，定义了所有配置流程的通用方法
    """

    def __init__(self, name: str, func_name: str, hass: HomeAssistant) -> None:
        self._name = name
        self.func_name = func_name
        self.hass = hass

    @abstractmethod
    async def async_parse_user_input(
        self, user_input: dict[str, Any], default_data: dict[str, Any] = None
    ) -> UserInputParseResult:
        """
        解析用户输入，返回解析后的结果
        """
        raise NotImplementedError

    async def async_whether_light_in_other_entries(
        self, light_entity_ids_set: set[str]
    ) -> tuple[set[str], ConfigEntry | None]:
        """
        检查light_entity_ids_set中的灯实体id是否在其他配置项中被使用，返回被使用了的灯实体和灯组实体id
        """

        for config_entry in await async_list_light_sync_entry(self.hass, func_name=FUNC_NAME_LIGHT_SYNC):
            if config_entry.title == self._name:
                continue
            func_data = config_entry.data["func_data"]
            if (light_entity_ids := func_data.get("light_entity_ids")) and (
                existing_light_entity_ids := light_entity_ids_set.intersection(light_entity_ids)
            ):
                return existing_light_entity_ids, config_entry
        return set(), None


class LightSyncFlowManager(OhMyLightBaseFlowManager):
    async def async_parse_user_input(
        self, user_input: dict[str, Any], default_data: dict[str, Any] = None
    ) -> UserInputParseResult:
        """
        解析用户输入，返回解析后的结果
        """

        if default_data:
            # 填充已选择的灯实体
            func_data = default_data.get("func_data")
            light_entity_ids = func_data.get("light_entity_ids", [])
            light_sync_group_entity_ids = func_data.get("light_sync_group_entity_ids", [])
            schema = vol.Schema(
                {
                    vol.Required(
                        "light_sync_entity_ids",
                        default=light_entity_ids + light_sync_group_entity_ids,
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="light", multiple=True),
                    ),
                }
            )
            return UserInputParseResult(
                create_entry=False,
                data_or_schema=schema,
                errors={},
            )

        if user_input and (light_sync_entity_ids := user_input.get("light_sync_entity_ids")):
            (
                light_entity_ids_set,
                light_group_entity_ids_set,
            ) = await async_parse_light_entity_ids(self.hass, light_sync_entity_ids)

            (
                existing_light_entity_ids,
                existing_config_entry,
            ) = await self.async_whether_light_in_other_entries(
                light_entity_ids_set.union(
                    await async_list_light_in_light_group(self.hass, light_group_entity_ids_set)
                ),
            )
            # 判断是否有灯实体id在其他配置项中被使用，如果有使用，则提示并让用户修改输入
            if existing_light_entity_ids:
                schema = vol.Schema(
                    {
                        vol.Required("light_sync_entity_ids", default=light_sync_entity_ids): selector.EntitySelector(
                            selector.EntitySelectorConfig(domain="light", multiple=True),
                        ),
                    }
                )
                return UserInputParseResult(
                    create_entry=False,
                    data_or_schema=schema,
                    errors={
                        "base": "light_entity_ids_in_other_entries",
                    },
                    description_placeholders={
                        "existing_light_entity_ids": ",".join(existing_light_entity_ids),
                        "existing_config_entry_id": existing_config_entry.title,
                    },
                )

            return UserInputParseResult(
                create_entry=True,
                data_or_schema={
                    "func_name": self.func_name,
                    "func_data": {
                        "light_entity_ids": list(light_entity_ids_set),
                        "light_group_entity_ids": list(light_group_entity_ids_set),
                    },
                },
                errors={},
            )

        # 选择多个灯
        schema = vol.Schema(
            {
                vol.Required("light_sync_entity_ids"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="light", multiple=True),
                ),
            }
        )
        return UserInputParseResult(
            create_entry=False,
            data_or_schema=schema,
            errors={},
        )


class LightSwitchBindFlowManager(OhMyLightBaseFlowManager):
    async def async_parse_user_input(
        self, user_input: dict[str, Any] | None = None, default_data: dict[str, Any] = None
    ) -> UserInputParseResult:
        if default_data:
            # 填充已选择的开关实体和灯实体
            func_data = default_data.get("func_data")
            switch_entity_ids = func_data.get("switch_entity_ids", [])
            light_entity_ids = func_data.get("light_entity_ids", [])
            schema = vol.Schema(
                {
                    vol.Required("switch_entity_ids", default=switch_entity_ids): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain=["switch", "binary_sensor"], multiple=True),
                    ),
                    vol.Required("light_entity_ids", default=light_entity_ids): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="light", multiple=True),
                    ),
                }
            )
            return UserInputParseResult(
                create_entry=False,
                data_or_schema=schema,
                errors={},
            )

        if (
            user_input
            and (light_entity_ids := user_input.get("light_entity_ids"))
            and (switch_entity_ids := user_input.get("switch_entity_ids"))
        ):
            return UserInputParseResult(
                create_entry=True,
                data_or_schema={
                    "func_name": self.func_name,
                    "func_data": {
                        "switch_entity_ids": switch_entity_ids,
                        "light_entity_ids": light_entity_ids,
                    },
                },
                errors={},
            )

        # 选择多个开关和多个灯
        schema = vol.Schema(
            {
                vol.Required("switch_entity_ids"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["switch", "binary_sensor"], multiple=True),
                ),
                vol.Required("light_entity_ids"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="light", multiple=True),
                ),
            }
        )
        return UserInputParseResult(
            create_entry=False,
            data_or_schema=schema,
            errors={},
        )


class LightEventBindFlowManager(OhMyLightBaseFlowManager):
    async def async_parse_user_input(
        self, user_input: dict[str, Any] | None = None, default_data: dict[str, Any] = None
    ) -> UserInputParseResult:
        if default_data:
            # 填充已选择的事件实体和灯实体
            func_data = default_data.get("func_data")
            event_entity_ids = func_data.get("event_entity_ids", [])
            light_entity_ids = func_data.get("light_entity_ids", [])
            schema = vol.Schema(
                {
                    vol.Required("event_entity_ids", default=event_entity_ids): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="event", multiple=True),
                    ),
                    vol.Required("light_entity_ids", default=light_entity_ids): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="light", multiple=True),
                    ),
                }
            )
            return UserInputParseResult(
                create_entry=False,
                data_or_schema=schema,
                errors={},
            )

        if (
            user_input
            and (light_entity_ids := user_input.get("light_entity_ids"))
            and (event_entity_ids := user_input.get("event_entity_ids"))
        ):
            return UserInputParseResult(
                create_entry=True,
                data_or_schema={
                    "func_name": self.func_name,
                    "func_data": {
                        "event_entity_ids": event_entity_ids,
                        "light_entity_ids": light_entity_ids,
                    },
                },
                errors={},
            )

        # 选择多个事件和多个灯
        schema = vol.Schema(
            {
                vol.Required("event_entity_ids"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="event", multiple=True),
                ),
                vol.Required("light_entity_ids"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="light", multiple=True),
                ),
            }
        )
        return UserInputParseResult(
            create_entry=False,
            data_or_schema=schema,
            errors={},
        )


FLOW_CLASS_MAP: dict[str, type[OhMyLightBaseFlowManager]] = {
    FUNC_NAME_LIGHT_SYNC: LightSyncFlowManager,
    FUNC_NAME_LIGHT_SWITCH_BIND: LightSwitchBindFlowManager,
    FUNC_NAME_LIGHT_EVENT_BIND: LightEventBindFlowManager,
}


class OhMyLightConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._name = None
        self._func_name = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        return OhMyLightOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        logger.debug(f"<{self._name}> user_input: {user_input}")
        if user_input:
            self._name = self._name or user_input.get("name")
            self._func_name = self._func_name or user_input.get("func_name")

        if not self._name or not self._func_name:
            schema = vol.Schema(
                {
                    vol.Optional("name", default="Rule1"): str,
                    vol.Required("func_name", default=FUNC_NAME_LIGHT_SYNC): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            translation_key="func_name",
                            options=list[str](FLOW_CLASS_MAP.keys()),
                        ),
                    ),
                }
            )
            return self.async_show_form(
                step_id="user",
                data_schema=schema,
            )

        await self.async_set_unique_id(self._name)
        self._abort_if_unique_id_configured()

        setattr(self, f"async_step_{self._func_name}", self.async_step_user)

        flow_class = FLOW_CLASS_MAP.get(self._func_name)
        if not flow_class:
            return self.async_abort(reason="unknown_func_name")
        func_flow = flow_class(self._name, self._func_name, self.hass)

        flow_result = await func_flow.async_parse_user_input(user_input)
        logger.debug(f"<{self._name}> async_step_{self._func_name}: {flow_result.as_dict()}")

        if not flow_result.create_entry:
            return self.async_show_form(
                step_id=self._func_name,
                data_schema=flow_result.data_or_schema,
                errors=flow_result.errors,
                description_placeholders=flow_result.description_placeholders,
            )

        return self.async_create_entry(title=self._name, data=flow_result.data_or_schema)


class OhMyLightOptionsFlow(OptionsFlow):
    """
    配置选项，用于用户修改配置
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        logger.debug(f"<{self.config_entry.title}> async_step_init: {user_input}")
        func_name = self.config_entry.data.get("func_name")
        entry_name = self.config_entry.title

        flow_class = FLOW_CLASS_MAP.get(func_name)
        if not flow_class:
            return self.async_abort(reason="unknown_func_name")
        func_flow = flow_class(entry_name, func_name, self.hass)

        if user_input is not None:
            # 用户有输入，尝试解析输入
            flow_result = await func_flow.async_parse_user_input(user_input)
            logger.debug(f"<{entry_name}> async_step_{func_name}: {flow_result.as_dict()}")
            if not flow_result.create_entry:
                return self.async_show_form(
                    step_id="init",
                    data_schema=flow_result.data_or_schema,
                    errors=flow_result.errors,
                    description_placeholders=flow_result.description_placeholders,
                )
            return self.async_create_entry(title=entry_name, data=flow_result.data_or_schema)

        # 用户没有输入，展示默认配置
        flow_result = await func_flow.async_parse_user_input(None, default_data=self.config_entry.data)
        return self.async_show_form(
            step_id="init",
            data_schema=flow_result.data_or_schema,
        )
