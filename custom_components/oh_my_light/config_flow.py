from typing import Any
import logging

from homeassistant.core import callback
from homeassistant.config_entries import ConfigFlow, OptionsFlow, ConfigEntry
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

import voluptuous as vol

from .const import DOMAIN

logger = logging.getLogger(__name__)


class OhMyuOhMyLightBaseFlow:
    """
    基础类
    """

    async def async_parse_light_entity_ids(
        self, light_entity_ids: list[str]
    ) -> tuple[set[str], set[str]]:
        """
        解析灯实体id列表，将普通灯和灯组id分别放到light_entity_ids和light_group_entity_ids列表中
        """
        light_entity_ids_set = set[str]()
        light_group_entity_ids_set = set[str]()
        while light_entity_ids:
            light_entity_id = light_entity_ids.pop(0)
            light_entity_state = self.hass.states.get(light_entity_id)
            if light_entity_state is None:
                logger.error(f"Light entity {light_entity_id} not found")
                continue
            if light_entity_state.attributes.get("is_group"):
                light_group_entity_ids_set.add(light_entity_id)
            else:
                light_entity_ids_set.add(light_entity_id)
        return light_entity_ids_set, light_group_entity_ids_set


class OhMyLightConfigFlow(ConfigFlow, OhMyuOhMyLightBaseFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        return OhMyLightOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
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
            menu_options=["light_sync", "light_switch_bind"],
        )

    async def async_step_func_choice(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        logger.debug(f"async_step_func_choice: {user_input}")
        return

    async def async_step_light_sync(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        logger.debug(f"async_step_light_sync: {user_input}")

        if user_input and (
            sync_light_entity_ids := user_input.get("sync_light_entity_ids")
        ):
            (
                light_entity_ids_set,
                light_group_entity_ids_set,
            ) = await self.async_parse_light_entity_ids(sync_light_entity_ids)
            return self.async_create_entry(
                title=self.context["name"],
                data={
                    "func_name": "light_sync",
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
            step_id="light_sync",
            data_schema=schema,
        )

    async def async_step_light_switch_bind(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        logger.debug(f"async_step_light_switch_bind: {user_input}")

        if (
            user_input
            and (sync_light_entity_ids := user_input.get("sync_light_entity_ids"))
            and (switch_entity_id := user_input.get("switch_entity_id"))
        ):
            (
                light_entity_ids_set,
                light_group_entity_ids_set,
            ) = await self.async_parse_light_entity_ids(sync_light_entity_ids)
            return self.async_create_entry(
                title=self.context["name"],
                data={
                    "func_name": "light_switch_bind",
                    "func_data": {
                        "switch_entity_id": switch_entity_id,
                        "light_entity_ids": list(light_entity_ids_set),
                        "light_group_entity_ids": list(light_group_entity_ids_set),
                    },
                },
            )

        # 选择一个开关和多个灯
        schema = vol.Schema(
            {
                vol.Required("switch_entity_id"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch"),
                ),
                vol.Required("sync_light_entity_ids"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="light", multiple=True),
                ),
            }
        )
        return self.async_show_form(
            step_id="light_switch_bind",
            data_schema=schema,
        )


class OhMyLightOptionsFlow(OptionsFlow, OhMyuOhMyLightBaseFlow):
    """
    配置选项，用于重新选取控制的灯实体
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        func_name = self.config_entry.data.get("func_name")
        if func_name not in ["light_sync", "light_switch_bind"]:
            logger.error(
                f"Unknown func name {func_name} in entry {self.config_entry.title}"
            )
            return self.async_abort(reason=f"Unknown func name: {func_name}")

        # 更新light_sync配置
        if (
            func_name == "light_sync"
            and user_input
            and (sync_light_entity_ids := user_input.get("sync_light_entity_ids"))
        ):
            (
                light_entity_ids_set,
                light_group_entity_ids_set,
            ) = await self.async_parse_light_entity_ids(sync_light_entity_ids)
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={
                    "func_name": "light_sync",
                    "func_data": {
                        "light_entity_ids": list(light_entity_ids_set),
                        "light_group_entity_ids": list(light_group_entity_ids_set),
                    },
                },
            )
            return self.async_create_entry(title="", data=None)

        # 更新light_switch_bind配置
        if (
            func_name == "light_switch_bind"
            and user_input
            and (switch_entity_id := user_input.get("switch_entity_id"))
            and (sync_light_entity_ids := user_input.get("sync_light_entity_ids"))
        ):
            (
                light_entity_ids_set,
                light_group_entity_ids_set,
            ) = await self.async_parse_light_entity_ids(sync_light_entity_ids)
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={
                    "func_name": "light_switch_bind",
                    "func_data": {
                        "switch_entity_id": switch_entity_id,
                        "light_entity_ids": list(light_entity_ids_set),
                        "light_group_entity_ids": list(light_group_entity_ids_set),
                    },
                },
            )
            return self.async_create_entry(title="", data=None)

        # 处理初始化选项
        if func_name == "light_sync":
            # 填充已选择的灯实体
            func_data = self.config_entry.data.get("func_data")
            sync_light_entity_ids = func_data.get("light_entity_ids")
            sync_light_group_entity_ids = func_data.get("light_group_entity_ids")
            schema = vol.Schema(
                {
                    vol.Required(
                        "sync_light_entity_ids",
                        default=sync_light_entity_ids + sync_light_group_entity_ids,
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="light", multiple=True),
                    ),
                }
            )
        else:
            # 填充已选择的开关实体和灯实体
            func_data = self.config_entry.data.get("func_data")
            switch_entity_id = func_data.get("switch_entity_id")
            sync_light_entity_ids = func_data.get("light_entity_ids")
            sync_light_group_entity_ids = func_data.get("light_group_entity_ids")
            schema = vol.Schema(
                {
                    vol.Required(
                        "switch_entity_id",
                        default=switch_entity_id,
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="switch"),
                    ),
                    vol.Required(
                        "sync_light_entity_ids",
                        default=sync_light_entity_ids + sync_light_group_entity_ids,
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="light", multiple=True),
                    ),
                }
            )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
        )
