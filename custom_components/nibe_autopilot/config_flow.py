"""Preset setup and menu-based native options, following the REP UI pattern."""

from copy import deepcopy

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import DEFAULTS, DOMAIN, LEGACY_WRITERS, REQUIRED_SOURCES, SETTINGS, SOURCES
from .engine import number, validate

GROUPS = (
    "pump",
    "rooms",
    "room_sources",
    "inputs",
    "comfort",
    "heating",
    "zones",
    "quiet",
    "electrical",
    "safety",
    "ownership",
)
BINDING_GROUPS = {"pump", "rooms", "room_sources", "inputs", "ownership"}


def suggested(hass):
    values = deepcopy(DEFAULTS)
    for key, (_, _, entity_id) in SOURCES.items():
        if hass.states.get(entity_id):
            values[key] = entity_id
    for key, entity_id in [
        ("comfort_target", "input_number.indoor_target_temperature"),
        ("heater_cap", "input_number.nibe_max_add_heat_kw"),
        ("heat_bias", "input_number.nibe_heat_bias"),
    ]:
        state = hass.states.get(entity_id)
        value = number(state.state) if state else None
        setting = SETTINGS[key]
        if (
            value is not None
            and setting.minimum <= value <= setting.maximum
            and abs(
                (value - setting.minimum) / setting.step
                - round((value - setting.minimum) / setting.step)
            )
            < 1e-6
        ):
            values[key] = value
    values["climates"] = sorted(
        s.entity_id
        for s in hass.states.async_all("climate")
        if s.entity_id.startswith("climate.thermostat_controller_")
    )
    values["indoor_sensors"] = (
        ["sensor.home_temperature_average"]
        if hass.states.get("sensor.home_temperature_average")
        else []
    )
    values["mains_sensors"] = [
        e
        for phase in "abc"
        if hass.states.get(e := f"sensor.shelly_pro_3em_3ct63_1_phase_{phase}_current")
    ]
    values["power_sensors"] = [
        e
        for phase in ("01", "11", "21")
        if hass.states.get(e := f"sensor.kincony_m30_ct_{phase}_power")
    ]
    values["legacy_writers"] = [e for e in LEGACY_WRITERS if hass.states.get(e)]
    return values


def fields(group, values):
    schema = {}

    def entity(key, domain, required=False, multiple=False):
        marker = vol.Required if required else vol.Optional
        options = (
            (
                {"default": values[key]}
                if required
                else {"description": {"suggested_value": values[key]}}
            )
            if key in values and values[key]
            else {}
        )
        schema[marker(key, **options)] = selector.EntitySelector(
            {"domain": domain, "multiple": multiple}
        )

    if group == "pump":
        for key in REQUIRED_SOURCES:
            entity(key, SOURCES[key][1], True)
    if group == "rooms":
        entity("climates", "climate", True, True)
        entity("indoor_sensors", "sensor", True, True)
    if group == "room_sources":
        # Named object keys are entity IDs, so changing room order cannot swap sensors.
        schema[vol.Optional("room_sources", default=values.get("room_sources", {}))] = (
            selector.ObjectSelector(
                {
                    "fields": {
                        room: {
                            "label": room,
                            "selector": {"entity": {"domain": "sensor"}},
                            "required": False,
                        }
                        for room in values.get("climates", [])
                    }
                }
            )
        )
    if group == "inputs":
        for key in ("outdoor_entity", "outdoor_fallback_entity", "brine_entity"):
            entity(key, "sensor")
        entity("mains_sensors", "sensor", True, True)
        entity("power_sensors", "sensor", False, True)
    for key, setting in SETTINGS.items():
        if setting.group == group:
            schema[vol.Required(key, default=values.get(key, setting.default))] = (
                selector.NumberSelector(
                    {
                        "min": setting.minimum,
                        "max": setting.maximum,
                        "step": setting.step,
                        "mode": "box",
                        **({"unit_of_measurement": setting.unit} if setting.unit else {}),
                    }
                )
            )
    if group == "quiet":
        schema[vol.Required("quiet_enabled", default=values.get("quiet_enabled", True))] = (
            selector.BooleanSelector()
        )
        for key in ("night_start", "night_end"):
            schema[vol.Required(key, default=values.get(key, DEFAULTS[key]))] = (
                selector.TimeSelector()
            )
    if group == "ownership":
        entity("legacy_writers", "automation", False, True)
        schema[
            vol.Required("ownership_reviewed", default=values.get("ownership_reviewed", False))
        ] = selector.BooleanSelector()
    return vol.Schema(schema)


def merge_group(group, original, user_input):
    result = dict(original)
    if group == "inputs":
        for key in ("outdoor_entity", "outdoor_fallback_entity", "brine_entity"):
            result.pop(key, None)
        result["power_sensors"] = []
    if group == "ownership":
        result["legacy_writers"] = []
    result.update(user_input)
    if group == "rooms":
        result["room_sources"] = {
            key: value
            for key, value in result.get("room_sources", {}).items()
            if key in result.get("climates", [])
        }
    return result


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self.draft = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlow()

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if self.draft is None:
            self.draft = suggested(self.hass)
        return await self._setup_group("pump", user_input)

    async def async_step_rooms(self, user_input=None):
        return await self._setup_group("rooms", user_input)

    async def async_step_inputs(self, user_input=None):
        return await self._setup_group("inputs", user_input)

    async def _setup_group(self, group, user_input):
        errors = {}
        if user_input is not None:
            self.draft = merge_group(group, self.draft, user_input)
            try:
                # Validate each page before advancing. Later pages may not have
                # selections yet; temporary placeholders never enter saved data.
                candidate = dict(self.draft)
                if group in ("pump", "rooms"):
                    candidate["mains_sensors"] = [
                        "sensor.phase_a",
                        "sensor.phase_b",
                        "sensor.phase_c",
                    ]
                if group == "pump":
                    candidate.update(climates=["climate.room"], indoor_sensors=["sensor.indoor"])
                validated = validate(candidate)
            except ValueError, TypeError:
                errors["base"] = "invalid_configuration"
            else:
                if group == "pump":
                    return await self.async_step_rooms()
                if group == "rooms":
                    return await self.async_step_inputs()
                self.draft = validated
                return await self.async_step_review()
        return self.async_show_form(
            step_id="user" if group == "pump" else group,
            data_schema=fields(group, self.draft),
            errors=errors,
        )

    async def async_step_review(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="NIBE Autopilot", data=self.draft)
        return self.async_show_form(step_id="review", data_schema=vol.Schema({}))


class OptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        return self.async_show_menu(step_id="init", menu_options=list(GROUPS))

    async def _group(self, group, user_input):
        current = DEFAULTS | dict(self.config_entry.data) | dict(self.config_entry.options)
        errors = {}
        if user_input is not None:
            runtime = getattr(self.config_entry, "runtime_data", None)
            if group in BINDING_GROUPS and runtime is not None and runtime.enabled:
                errors["base"] = "disable_first"
            else:
                try:
                    new = validate(merge_group(group, current, user_input))
                except ValueError, TypeError:
                    errors["base"] = "invalid_configuration"
                else:
                    # Full merged options preserve all unrelated groups and optional removals.
                    for key in SOURCES:
                        new.setdefault(key, "")
                    return self.async_create_entry(title="", data=new)
        return self.async_show_form(
            step_id=group, data_schema=fields(group, current), errors=errors
        )


def _option_step(group):
    async def step(self, user_input=None):
        return await self._group(group, user_input)

    return step


for _group_name in GROUPS:
    setattr(OptionsFlow, f"async_step_{_group_name}", _option_step(_group_name))
