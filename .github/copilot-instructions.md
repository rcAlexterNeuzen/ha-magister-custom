# GitHub Copilot Instructions — ha-magister-custom

This is a Home Assistant custom integration for the Magister school information system (Dutch education). It is written in Python (backend) and YAML (Lovelace dashboard).

---

## Project structure

```
custom_components/magister_custom/
├── __init__.py        # HA integration setup & platform loading
├── auth.py            # Magister OIDC authentication client
├── calendar.py        # CalendarEntity per student
├── config_flow.py     # Config/options/re-auth UI flow
├── const.py           # All constants (domain, config keys, scan interval)
├── coordinator.py     # DataUpdateCoordinator, all dataclasses, all API parsing
├── manifest.json      # Integration metadata & version
├── sensor.py          # All SensorEntity subclasses
└── strings.json       # Dutch UI strings for config flow

lovelace_dashboard.yaml   # Lovelace dashboard (Jinja2 markdown cards + apexcharts)
README.md                 # User-facing documentation (Dutch)
```

---

## Mandatory rules — always apply these

### 1. Update README.md

Every change that affects entities, sensor attributes, API behaviour, or dashboard cards **must** be reflected in `README.md`:

- Add a new `### vX.Y.Z` entry at the top of the **Changelog** section describing what changed.
- Update the **Sensoren** table if attributes are added, removed, or renamed.
- Update the **Lovelace dashboard** table if cards are added or removed.
- Bump the version in `manifest.json` to match the new changelog entry.
- Keep all existing changelog entries intact below the new one.

### 2. Update lovelace_dashboard.yaml

Every change that adds or modifies sensor attributes **must** also update `lovelace_dashboard.yaml` so the dashboard reflects the new data:

- New attributes → add or update the relevant markdown card template.
- New sensors → add a card for the new sensor.
- Removed attributes → remove them from any card that references them.
- Entity IDs in the dashboard follow the pattern `sensor.magister_lieke_neuzen_magister_lieke_neuzen_<suffix>`. Update them if the suffix changes.

### 3. Versioning and GitHub releases

Every change that bumps `manifest.json` version **automatically creates a GitHub release** via `.github/workflows/release.yml` when pushed to `main`/`master`. HACS uses these release tags to notify users of updates.

Rules:
- The tag format is `v{version}` (e.g. `v1.0.9`). The workflow creates it automatically — **do not create tags manually**.
- The version in `manifest.json` must be bumped **in the same commit** as the code change. Pushing to `main` with the same version as an existing release does nothing (idempotent check in the workflow).
- `hacs.json` → `homeassistant` sets the minimum HA version shown in HACS. Update it only when a new HA API is required.

### 4. Follow the existing code conventions

#### Python

- All dataclasses live in `coordinator.py`. Add new fields **with a default value** (`field: type = default`) so existing construction call-sites do not break.
- Every dataclass must have an `as_dict()` method that includes all fields. New fields must be added there too.
- Parsing helpers (`_parse_grades`, `_parse_absences`, etc.) live at module level in `coordinator.py`. Always handle both camelCase and PascalCase API keys: `item.get("key") or item.get("Key")`.
- Sensor attributes are exposed via `extra_state_attributes`. Never put large lists directly in the sensor `state` — state must be a scalar (str, int, float).
- Use `_safe_float()` for any value that might be None or non-numeric. Never call `float()` directly on API data.
- All datetime parsing goes through `_parse_dt()`. Never call `datetime.fromisoformat()` directly on API strings.
- Log warnings (`_LOGGER.warning`) for failures in data fetching that affect the user. Log debug (`_LOGGER.debug`) for internal flow and optional features.
- Keep `const.py` as the single source of truth for all string constants and configuration keys.

#### Jinja2 / Lovelace templates

- Always use `{%- set ... -%}` (both dashes) for tags that produce no output (variable assignments, inner loops).
- For tags that come **directly after an output line** and must preserve the preceding newline, use `{% endif -%}` or `{% endfor -%}` (no leading dash). Using `{%- endif -%}` after an output line will eat the newline and concatenate results.
- Accumulate lists or totals inside loops using `namespace()`. Never reassign plain variables inside a loop.
- Access sensor attributes with `state_attr('sensor.entity_id', 'attribute_name')`. Always guard with `or []` / `or {}` for list/dict attributes that may be None.
- Charts use `custom:apexcharts-card` (HACS). Always set `graph_span` (e.g. `2year`) to define the x-axis window — without it the chart defaults to a tiny time range and shows only one data point. Add `update_interval` alongside `graph_span` to control refresh frequency. Place `yaxis` min/max/decimals inside `apex_config`, **not** at the card root level (root-level `yaxis` is the apexcharts-card multi-axis config, a different thing entirely).

#### YAML / manifest

- `manifest.json` version follows semantic versioning. Increment the patch version for bugfixes, minor for new features.
- `hacs.json` stays unchanged unless the minimum HA version requirement changes.

---

## Data flow overview

```
Magister API
  └─ MagisterCoordinator._fetch_all()
       └─ _fetch_student()
            ├─ GET /personen/{id}/afspraken       → _parse_appointments() → StudentData.appointments
            ├─ GET /personen/{id}/roosterwijzigingen → _parse_schedule_changes() → StudentData.schedule_changes
            ├─ GET /personen/{id}/cijfers/laatste  → _parse_grades()       → StudentData.grades
            └─ GET /personen/{id}/absenties        → _parse_absences()     → StudentData.absences

StudentData
  └─ sensor.py / calendar.py read coordinator.data.students[name]
       ├─ MagisterGradesSensor       → state=latest value, attrs: cijfers, cijfers_per_periode, aantal
       ├─ MagisterHomeworkSensor     → state=count, attrs: huiswerk
       ├─ MagisterOverviewSensor     → state=lessons today, attrs: various overview fields
       ├─ MagisterAbsencesSensor     → state=count, attrs: absenties
       ├─ MagisterScheduleChangesSensor → state=count, attrs: wijzigingen
       ├─ MagisterNextAppointmentSensor → state=formatted datetime
       └─ MagisterCalendar           → CalendarEntity with async_get_events()
```

---

## Key dataclasses (coordinator.py)

| Class | Key fields |
|---|---|
| `Grade` | `subject`, `subject_name`, `description`, `value`, `weight`, `entered_on`, `period` |
| `Appointment` | `start`, `end`, `subject`, `location`, `description`, `title`, `content`, `teachers`, `info_type`, `is_homework`, `is_cancelled` |
| `Absence` | `start`, `end`, `description`, `reason`, `handled`, `counts`, `lesson`, `period` |
| `ScheduleChange` | `start`, `end`, `subject`, `location`, `description` |
| `StudentData` | `name`, `student_id`, `appointments`, `grades`, `schedule_changes`, `absences`, `appointments_today`, `homework_count`, `next_appointment` |

---

## What NOT to do

- Do not add `[:N]` slices when exposing attributes — expose all data and let the dashboard template filter.
- Do not omit `graph_span` in apexcharts-card charts — without it the x-axis defaults to the current timestamp and only one data point is visible.
- Do not put `yaxis` min/max at the apexcharts-card root level — put it inside `apex_config`.
- Do not call the Magister API from sensor/calendar classes — all API logic belongs in `coordinator.py`.
- Do not create new files for data models or parsing helpers — keep them in `coordinator.py`.
- Do not hardcode student names or entity IDs in Python — derive them from `student_name` and `slug`.
