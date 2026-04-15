"""Sensor platform for Magister.

Per student the following sensors are created:

  sensor.magister_<name>                  – aantal lessen vandaag (overview)
  sensor.magister_<name>_next_appointment – volgende les / afspraak
  sensor.magister_<name>_grades           – laatste 10 cijfers (state = meest recente)
  sensor.magister_<name>_homework         – aantal huiswerkopdrachten
  sensor.magister_<name>_schedule_changes – aantal roosterwijzigingen
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import Appointment, MagisterCoordinator, MagisterData, StudentData

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MagisterCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = []
    data: MagisterData = coordinator.data

    for student_name in data.students:
        slug = _slug(student_name)
        entities += [
            MagisterOverviewSensor(coordinator, student_name, slug),
            MagisterNextAppointmentSensor(coordinator, student_name, slug),
            MagisterGradesSensor(coordinator, student_name, slug),
            MagisterHomeworkSensor(coordinator, student_name, slug),
            MagisterScheduleChangesSensor(coordinator, student_name, slug),
        ]

    async_add_entities(entities, update_before_add=False)


def _slug(name: str) -> str:
    """Convert a student name to a safe entity ID slug."""
    return name.lower().replace(" ", "_").replace("-", "_")


def _fmt_appointment(apt: Appointment | None) -> str:
    if apt is None:
        return "Geen"
    subject = apt.subject or "Afspraak"
    start = apt.start.astimezone().strftime("%d-%m %H:%M") if apt.start else "?"
    return f"{subject} om {start}"


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class _MagisterBaseSensor(CoordinatorEntity[MagisterCoordinator], SensorEntity):
    """Shared base for all Magister sensors."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: MagisterCoordinator,
        student_name: str,
        slug: str,
        sensor_suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._student_name = student_name
        self._slug = slug
        self._attr_unique_id = f"magister_{coordinator.entry.entry_id}_{slug}_{sensor_suffix}"
        self._attr_entity_id = f"sensor.magister_{slug}_{sensor_suffix}"

    @property
    def _student(self) -> StudentData | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.students.get(self._student_name)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self._student is not None

    @property
    def device_info(self) -> dict[str, Any]:
        return {
            "identifiers": {(DOMAIN, f"{self.coordinator.entry.entry_id}_{self._slug}")},
            "name": f"Magister – {self._student_name}",
            "manufacturer": "Magister",
            "model": "Schoolinformatie",
        }


# ---------------------------------------------------------------------------
# Overview sensor
# ---------------------------------------------------------------------------

class MagisterOverviewSensor(_MagisterBaseSensor):
    """Main sensor: state = number of lessons today."""

    _attr_icon = "mdi:school"

    def __init__(self, coordinator: MagisterCoordinator, student_name: str, slug: str) -> None:
        super().__init__(coordinator, student_name, slug, "overview")
        self._attr_name = f"Magister {student_name}"
        self._attr_unique_id = f"magister_{coordinator.entry.entry_id}_{slug}_overview"

    @property
    def state(self) -> int:
        if (s := self._student) is None:
            return 0
        return s.appointments_today

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._student
        if s is None:
            return {}

        next_apt = s.next_appointment
        attrs: dict[str, Any] = {
            "naam": s.name,
            "afspraken_vandaag": s.appointments_today,
            "huiswerk_aantal": s.homework_count,
            "roosterwijzigingen": len(s.schedule_changes),
            "volgende_afspraak": _fmt_appointment(next_apt),
            "laatste_cijfer": s.grades[0].value if s.grades else "–",
        }
        if next_apt:
            attrs["volgende_vak"] = next_apt.subject
            attrs["volgende_locatie"] = next_apt.location
        return attrs


# ---------------------------------------------------------------------------
# Next appointment sensor
# ---------------------------------------------------------------------------

class MagisterNextAppointmentSensor(_MagisterBaseSensor):
    """State = formatted start time of the next upcoming lesson."""

    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: MagisterCoordinator, student_name: str, slug: str) -> None:
        super().__init__(coordinator, student_name, slug, "next_appointment")
        self._attr_name = f"Magister {student_name} volgende afspraak"

    @property
    def state(self) -> str:
        s = self._student
        if s is None or s.next_appointment is None:
            return "Geen"
        apt = s.next_appointment
        return apt.start.astimezone().strftime("%Y-%m-%d %H:%M")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._student
        if s is None or s.next_appointment is None:
            return {}
        apt = s.next_appointment
        return apt.as_dict()


# ---------------------------------------------------------------------------
# Grades sensor
# ---------------------------------------------------------------------------

class MagisterGradesSensor(_MagisterBaseSensor):
    """State = most recent grade value; attributes = last 10 grades."""

    _attr_icon = "mdi:school-outline"

    def __init__(self, coordinator: MagisterCoordinator, student_name: str, slug: str) -> None:
        super().__init__(coordinator, student_name, slug, "grades")
        self._attr_name = f"Magister {student_name} cijfers"

    @property
    def state(self) -> str:
        s = self._student
        if s is None or not s.grades:
            return "–"
        return s.grades[0].value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._student
        if s is None:
            return {}
        return {
            "cijfers": [g.as_dict() for g in s.grades[:10]],
        }


# ---------------------------------------------------------------------------
# Homework sensor
# ---------------------------------------------------------------------------

class MagisterHomeworkSensor(_MagisterBaseSensor):
    """State = number of upcoming homework items."""

    _attr_icon = "mdi:book-open-page-variant"

    def __init__(self, coordinator: MagisterCoordinator, student_name: str, slug: str) -> None:
        super().__init__(coordinator, student_name, slug, "homework")
        self._attr_name = f"Magister {student_name} huiswerk"

    @property
    def state(self) -> int:
        s = self._student
        return s.homework_count if s else 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._student
        if s is None:
            return {}
        hw = [a.as_dict() for a in s.appointments if a.is_homework and not a.is_cancelled]
        return {"huiswerk": hw}


# ---------------------------------------------------------------------------
# Schedule changes sensor
# ---------------------------------------------------------------------------

class MagisterScheduleChangesSensor(_MagisterBaseSensor):
    """State = number of schedule changes in the fetch window."""

    _attr_icon = "mdi:calendar-alert"

    def __init__(self, coordinator: MagisterCoordinator, student_name: str, slug: str) -> None:
        super().__init__(coordinator, student_name, slug, "schedule_changes")
        self._attr_name = f"Magister {student_name} roosterwijzigingen"

    @property
    def state(self) -> int:
        s = self._student
        return len(s.schedule_changes) if s else 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._student
        if s is None:
            return {}
        return {"wijzigingen": [c.as_dict() for c in s.schedule_changes[:20]]}
