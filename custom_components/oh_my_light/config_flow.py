import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import DOMAIN, FUNC_NAME_LIGHT_SWITCH_BIND, FUNC_NAME_LIGHT_SYNC
from .utils import (
    async_list_light_in_light_group,
    async_list_light_sync_entry,
    async_parse_light_entity_ids,
)

logger = logging.getLogger(__name__)


class OhMyuOhMyLightBaseFlow:
    """
    基础类
    """

    async def async_if_light_in_other_entries(
        self, light_entity_ids_set: set[str]
    ) -> tuple[set[str], ConfigEntry | None]:
        """
        检查light_entity_ids_set中的灯实体id是否在其他配置项中被使用，返回被使用了的灯实体和灯组实体id
        """
        current_entry_id = None
        if isinstance(self, ConfigFlow):
            current_entry_id = self.context["name"]
        elif isinstance(self, OptionsFlow):
            current_entry_id = self.config_entry.entry_id
        else:
            return set(), None

        for config_entry in await async_list_light_sync_entry(self.hass, func_name=FUNC_NAME_LIGHT_SYNC):
            if config_entry.entry_id == current_entry_id:
                continue
            func_data = config_entry.data["func_data"]
            if (light_entity_ids := func_data.get("light_entity_ids")) and (
                existing_light_entity_ids := light_entity_ids_set.intersection(light_entity_ids)
            ):
                return existing_light_entity_ids, config_entry
        return set(), None


class OhMyLightConfigFlow(ConfigFlow, OhMyuOhMyLightBaseFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        return OhMyLightOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        logger.debug(f"async_step_user: {user_input}")

        if not user_input or not user_input.get("name"):
            schema = vol.Schema(
                {
                    vol.Optional("name", default="Rule1"): str,
                }
            )
            return self.async_show_form(
                step_id="user",
                data_schema=schema,
            )

        name = user_input.get("name")
        self.context["name"] = name
        await self.async_set_unique_id(name)
        self._abort_if_unique_id_configured()
        return self.async_show_menu(
            step_id="func_choice",
            menu_options=[
                FUNC_NAME_LIGHT_SYNC,
                FUNC_NAME_LIGHT_SWITCH_BIND,
            ],
        )

    async def async_step_func_choice(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        logger.debug(f"async_step_func_choice: {user_input}")
        return

    async def async_step_light_sync(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        logger.debug(f"async_step_light_sync: {user_input}")
        if user_input and (sync_light_entity_ids := user_input.get("sync_light_entity_ids")):
            (
                light_entity_ids_set,
                light_group_entity_ids_set,
            ) = await async_parse_light_entity_ids(self.hass, sync_light_entity_ids)

            (
                existing_light_entity_ids,
                existing_config_entry,
            ) = await self.async_if_light_in_other_entries(
                light_entity_ids_set.union(
                    await async_list_light_in_light_group(self.hass, light_group_entity_ids_set)
                ),
            )
            # 判断是否有灯实体id在其他配置项中被使用，如果有使用，则提示并让用户修改输入
            if existing_light_entity_ids:
                schema = vol.Schema(
                    {
                        vol.Required("sync_light_entity_ids", default=sync_light_entity_ids): selector.EntitySelector(
                            selector.EntitySelectorConfig(domain="light", multiple=True),
                        ),
                    }
                )
                return self.async_show_form(
                    step_id=FUNC_NAME_LIGHT_SYNC,
                    data_schema=schema,
                    description_placeholders={
                        "existing_light_entity_ids": ",".join(existing_light_entity_ids),
                        "existing_config_entry_id": existing_config_entry.title,
                    },
                    errors={
                        "base": "light_entity_ids_in_other_entries",
                    },
                )

            return self.async_create_entry(
                title=self.context["name"],
                data={
                    "func_name": FUNC_NAME_LIGHT_SYNC,
                    "func_data": {
                        "light_entity_ids": list(light_entity_ids_set),
                        "light_group_entity_ids": list(light_group_entity_ids_set),
                    },
                },
            )

        # 选择多个灯
        schema = vol.Schema(
            {
                vol.Required("sync_light_entity_ids"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="light", multiple=True),
                ),
            }
        )
        return self.async_show_form(
            step_id=FUNC_NAME_LIGHT_SYNC,
            data_schema=schema,
        )

    async def async_step_light_switch_bind(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        logger.debug(f"async_step_light_switch_bind: {user_input}")

        if (
            user_input
            and (light_entity_ids := user_input.get("light_entity_ids"))
            and (is_wireless := user_input.get("is_wireless")) is not None
            and (switch_entity_ids := user_input.get("switch_entity_ids"))
        ):
            return self.async_create_entry(
                title=self.context["name"],
                data={
                    "func_name": FUNC_NAME_LIGHT_SWITCH_BIND,
                    "func_data": {
                        "switch_entity_ids": switch_entity_ids,
                        "is_wireless": is_wireless,
                        "light_entity_ids": light_entity_ids,
                    },
                },
            )

        # 选择多个开关和多个灯
        schema = vol.Schema(
            {
                vol.Required("switch_entity_ids"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch", multiple=True),
                ),
                vol.Required("is_wireless", default=False): bool,
                vol.Required("light_entity_ids"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="light", multiple=True),
                ),
            }
        )
        return self.async_show_form(
            step_id=FUNC_NAME_LIGHT_SWITCH_BIND,
            data_schema=schema,
        )


class OhMyLightOptionsFlow(OptionsFlow, OhMyuOhMyLightBaseFlow):
    """
    配置选项，用于用户修改配置
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        func_name = self.config_entry.data.get("func_name")
        if func_name not in [FUNC_NAME_LIGHT_SYNC, FUNC_NAME_LIGHT_SWITCH_BIND]:
            logger.error(f"Unknown func name {func_name} in entry {self.config_entry.title}")
            return self.async_abort(reason=f"Unknown func name: {func_name}")

        # 更新light_sync配置
        if (
            func_name == FUNC_NAME_LIGHT_SYNC
            and user_input
            and (light_entity_ids := user_input.get("sync_light_entity_ids", []))
        ):
            (
                light_entity_ids_set,
                light_group_entity_ids_set,
            ) = await async_parse_light_entity_ids(self.hass, light_entity_ids)
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={
                    "func_name": FUNC_NAME_LIGHT_SYNC,
                    "func_data": {
                        "light_entity_ids": list(light_entity_ids_set),
                        "light_group_entity_ids": list(light_group_entity_ids_set),
                    },
                },
            )
            logger.debug(f"Updated light sync to config: {self.config_entry.data}")
            return self.async_create_entry(title="", data=None)

        # 更新light_switch_bind配置
        if (
            func_name == FUNC_NAME_LIGHT_SWITCH_BIND
            and user_input
            and (switch_entity_ids := user_input.get("switch_entity_ids"))
            and (light_entity_ids := user_input.get("light_entity_ids"))
            and (is_wireless := user_input.get("is_wireless")) is not None
        ):
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={
                    "func_name": FUNC_NAME_LIGHT_SWITCH_BIND,
                    "func_data": {
                        "switch_entity_ids": switch_entity_ids,
                        "is_wireless": is_wireless,
                        "light_entity_ids": light_entity_ids,
                    },
                },
            )
            logger.debug(f"Updated light switch bind to config: {self.config_entry.data}")
            return self.async_create_entry(title="", data=None)

        # 处理初始化选项
        if func_name == FUNC_NAME_LIGHT_SYNC:
            # 填充已选择的灯实体
            func_data = self.config_entry.data.get("func_data")
            light_entity_ids = func_data.get("light_entity_ids", [])
            sync_light_group_entity_ids = func_data.get("light_group_entity_ids", [])
            schema = vol.Schema(
                {
                    vol.Required(
                        "sync_light_entity_ids",
                        default=light_entity_ids + sync_light_group_entity_ids,
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="light", multiple=True),
                    ),
                }
            )
        elif func_name == FUNC_NAME_LIGHT_SWITCH_BIND:
            # 填充已选择的开关实体和灯实体
            func_data = self.config_entry.data.get("func_data")
            switch_entity_ids = func_data.get("switch_entity_ids", [])
            is_wireless = func_data.get("is_wireless", False)
            light_entity_ids = func_data.get("light_entity_ids", [])
            schema = vol.Schema(
                {
                    vol.Required("switch_entity_ids", default=switch_entity_ids): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="switch", multiple=True),
                    ),
                    vol.Required("is_wireless", default=is_wireless): bool,
                    vol.Required("light_entity_ids", default=light_entity_ids): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="light", multiple=True),
                    ),
                }
            )
        else:
            logger.error(f"Unknown func name {func_name} in entry {self.config_entry.title}")
            return self.async_abort(reason=f"Unknown func name: {func_name}")

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
        )
