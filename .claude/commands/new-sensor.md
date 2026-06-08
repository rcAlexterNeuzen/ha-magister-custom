---
description: Scaffold a new sensor entity for the Magister integration. Pass the sensor name/purpose as argument (e.g. /new-sensor study-load).
---

Add a new sensor entity to ha-magister-custom for: **$ARGUMENTS**

Follow the architecture and conventions from `.github/copilot-instructions.md` exactly.

## Steps

1. **coordinator.py** — if the sensor exposes new data from the API:
   - Add fields to the relevant dataclass (`StudentData`, `Grade`, etc.) **with a default value** so existing call sites don't break.
   - Add the field to the dataclass `as_dict()` method.
   - Add parsing logic in the appropriate `_parse_*()` helper, handling both camelCase and PascalCase API keys.
   - Update `_fetch_student()` if a new API endpoint is needed.

2. **sensor.py** — create a new `SensorEntity` subclass:
   - `name`: follow the `magister_<student_slug>_<suffix>` pattern.
   - `state`: must be a scalar (str, int, or float) — never a list or dict.
   - `extra_state_attributes`: expose lists/dicts here, not in state.
   - Use `_safe_float()` for any numeric value from the API.
   - Register the new sensor in `async_setup_entry()`.

3. **lovelace_dashboard.yaml** — add a markdown card for the new sensor using `integration_entities('magister_custom')` auto-discovery. Follow the existing Jinja2 conventions (namespace for loops, `{%- set -%}` for assignments).

4. **strings.json** — add Dutch UI labels if the sensor introduces new config options.

5. **README.md** — add the new entity to the Sensoren table and prepare a changelog entry (do not bump the version yet — use `/bump-version` for that).

6. Show a summary of all files changed.
