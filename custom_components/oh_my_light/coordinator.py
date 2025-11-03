import logging
import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import Event, HomeAssistant, callback, Context
from homeassistant.helpers.event import async_track_state_change_event

logger = logging.getLogger(__name__)

LIGHT_SERVICES = {
    STATE_ON: "turn_on",
    STATE_OFF: "turn_off",
}


class OhMyLightCoordinator:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        self.hass = hass
        self.integration_entry = entry
        self.unsub_callbacks: list[callable] = []
        # 被扇出的实体id，用于避免循环更新
        self._fanned_out_entity_ids: set[str] = set()
        self._last_update_timestamp = 0

    async def async_setup(self):
        logger.debug("Setting up Oh My Light coordinator")
        await self._async_setup_listeners()

    async def async_unload(self):
        logger.debug("Unloading Oh My Light coordinator")
        for unsub_callback in self.unsub_callbacks:
            unsub_callback()
        self.unsub_callbacks.clear()

    async def _async_setup_listeners(self):
        light_entity_ids = self.integration_entry.data["light_entity_ids"]
        if not light_entity_ids:
            logger.error("No light entity ids found in config entry")
            return

        logger.debug(f"Listen light entity ids: {light_entity_ids}")
        unsub_callback = async_track_state_change_event(
            self.hass,
            light_entity_ids,
            self._async_handle_light_state_change,
        )
        self.unsub_callbacks.append(unsub_callback)

    @callback
    async def _async_handle_light_state_change(self, event: Event):
        logger.debug(f"Light entity state change: {event.as_dict()}")

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

        # 如果上次更新时间距离现在大于1秒，清空被扇出的实体id
        if (
            not self._last_update_timestamp
            or event.time_fired - self._last_update_timestamp
            > datetime.timedelta(seconds=3)
        ):
            logger.debug("Clear fanned out entity ids")
            self._fanned_out_entity_ids.clear()

        # 如果变更的entity_id在被扇出的实体id中，从被扇出的实体id中删除该entity_id并直接返回
        entity_id = event.data.get("entity_id")
        if entity_id in self._fanned_out_entity_ids:
            logger.debug(f"Ingore this event, entity {entity_id} is fanned out")
            # self._fanned_out_entity_ids.remove(entity_id)
            return

        # 将需要变更的实体添加到被扇出的实体id中
        self._fanned_out_entity_ids.update(
            [
                e
                for e in self.integration_entry.data["light_entity_ids"]
                if e != entity_id
            ]
        )

        for light_entity_id in set[str](self._fanned_out_entity_ids):
            await self._set_light_entity_state(
                light_entity_id, state, new_state.attributes, event.context
            )

        self._last_update_timestamp = event.time_fired

    async def _set_light_entity_state(
        self,
        entity_id: str,
        desired_state: str,
        desired_attributes: dict = None,
        context: Context = None,
    ) -> None:
        logger.debug(
            f"Setting entity {entity_id} to state {desired_state} with attributes {desired_attributes}"
        )
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
            await self.hass.services.async_call(
                domain,
                LIGHT_SERVICES[desired_state],
                {**{"entity_id": entity_id, **desired_attributes}},
            )
            logger.info(
                f"Successfully set {entity_id} to state {desired_state} with attributes {desired_attributes}"
            )
        except Exception:
            logger.error(
                f"Failed to set {entity_id} to state {desired_state} with attributes {desired_attributes}",
                exc_info=True,
            )
