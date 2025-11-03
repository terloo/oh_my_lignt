from typing import Any
import logging

from homeassistant.core import callback
from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

import voluptuous as vol

from .const import DOMAIN

logger = logging.getLogger(__name__)


class OhMyLightConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OhMyLightOptionsFlow(config_entry)

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

        if user_input is not None and user_input.get("light_entity_ids") is not None:
            return self.async_create_entry(
                title=self.context["name"],
                data=user_input,
            )

        # 选择多个灯
        schema = vol.Schema(
            {
                vol.Required("light_entity_ids"): selector.EntitySelector(
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
            user_input is not None
            and user_input.get("switch_entity_id") is not None
            and user_input.get("light_entity_ids") is not None
        ):
            return self.async_create_entry(
                title=self.context["name"],
                data=user_input,
            )

        # 选择一个开关和多个灯
        schema = vol.Schema(
            {
                vol.Required("switch_entity_id"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch"),
                ),
                vol.Required("light_entity_ids"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="light", multiple=True),
                ),
            }
        )
        return self.async_show_form(
            step_id="light_switch_bind",
            data_schema=schema,
        )


class OhMyLightOptionsFlow(OptionsFlow):
    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        logger.debug(f"async_step_init: {user_input}")
