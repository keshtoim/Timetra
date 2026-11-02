import datetime
from dataclasses import dataclass, field

from timetra.db.repo import Repo

ODD, EVEN = 1, 2
# понедельник первой недели 2024 года: от него считаем чётность, номер недели в году сбивается на стыке лет
WEEK_ANCHOR = datetime.date(2024, 1, 1)
DATE_FORMAT = "%d.%m.%Y"
SUNDAY = 7


def week_for_date(date: datetime.date, offset: int) -> int:
    """offset = 1, если у школы нечётная неделя начинается на неделю позже нашего отсчёта."""
    weeks = (date - WEEK_ANCHOR).days // 7
    return ODD if (weeks + offset) % 2 == 0 else EVEN


def parse_date(text: str) -> datetime.date | None:
    try:
        return datetime.datetime.strptime(text.strip(), DATE_FORMAT).date()
    except ValueError:
        return None


@dataclass
class SubstitutionCheck:
    room_busy: str | None = None
    warnings: list[str] = field(default_factory=list)


def day_lessons(repo: Repo, version, date: datetime.date, offset: int):
    """Всё, что идёт в этот день: уроки расписания с заменами и дополнительные уроки."""
    if date.isoweekday() == SUNDAY:
        return []
    rows = [
        *repo.lessons_on_date(version, week_for_date(date, offset), date.isoweekday(), date.isoformat()),
        *repo.extras_on_date(version, date.isoformat()),
    ]
    return sorted(rows, key=lambda r: (r["grade"], r["letter"], r["eff_number"], r["subgroup"]))


def _overlapping_slots(repo: Repo, slot_id) -> set[int]:
    slots = repo.slots()
    target = next(s for s in slots if s["id"] == slot_id)
    return {
        s["id"] for s in slots
        if s["id"] == slot_id or (
            s["starts_at"] and s["ends_at"] and target["starts_at"] and target["ends_at"]
            and s["starts_at"] < target["ends_at"] and target["starts_at"] < s["ends_at"]
        )
    }


def _others_at(repo: Repo, version, date, offset, slot_id, skip):
    """Идущие одновременно уроки дня. Смотрим на день с заменами: учитель мог уже кого-то заменять."""
    together = _overlapping_slots(repo, slot_id)
    for other in day_lessons(repo, version, date, offset):
        same = skip is not None and (other["lesson_id"], other["extra_id"]) == (skip["lesson_id"], skip["extra_id"])
        if not same and other["eff_slot_id"] in together and not other["is_cancelled"]:
            yield other


def _check(repo, version, date, offset, slot_id, class_id, subgroup, teacher_id, subject_id, room_id, skip) -> SubstitutionCheck:
    result = SubstitutionCheck()
    teachers = {t["id"]: t["short"] for t in repo.teachers()}
    subjects = {s["id"]: s["name"] for s in repo.subjects()}
    for other in _others_at(repo, version, date, offset, slot_id, skip):
        if room_id and other["eff_room_id"] == room_id:
            number = next(r["number"] for r in repo.rooms() if r["id"] == room_id)
            result.room_busy = f"Кабинет {number} занят: там урок {other['class_name']}"
        if other["eff_teacher_id"] == teacher_id:
            result.warnings.append(f"Учитель {teachers[teacher_id]} в это время ведёт урок в {other['class_name']}")
        if other["class_id"] == class_id and (other["subgroup"] == subgroup or not other["subgroup"] or not subgroup):
            result.warnings.append(f"У класса {other['class_name']} в это время уже есть урок")
    if (date.isoweekday(), slot_id) in repo.teacher_off(teacher_id):
        result.warnings.append(f"Учитель {teachers[teacher_id]} в это время не может вести уроки")
    taught = repo.teacher_subject_ids(teacher_id)
    if taught and subject_id not in taught:
        result.warnings.append(f"{teachers[teacher_id]} не отмечен как учитель предмета «{subjects[subject_id]}»")
    return result


def check_substitution(repo: Repo, version, date, offset, lesson, teacher_id, subject_id, room_id, slot_id=None) -> SubstitutionCheck:
    return _check(
        repo, version, date, offset, slot_id or lesson["eff_slot_id"], lesson["class_id"], lesson["subgroup"],
        teacher_id, subject_id, room_id, lesson,
    )


def check_extra(repo: Repo, version, date, offset, class_id, subgroup, slot_id, teacher_id, subject_id, room_id, extra=None) -> SubstitutionCheck:
    return _check(repo, version, date, offset, slot_id, class_id, subgroup, teacher_id, subject_id, room_id, extra)


def free_teacher_ids(repo: Repo, version, date, offset, lesson, slot_id=None) -> set[int]:
    """Кто свободен на этом уроке: для подсказок в списке учителей."""
    slot = slot_id or lesson["eff_slot_id"]
    busy = {x["eff_teacher_id"] for x in _others_at(repo, version, date, offset, slot, lesson)}
    return {
        t["id"] for t in repo.teachers()
        if t["id"] not in busy and (date.isoweekday(), slot) not in repo.teacher_off(t["id"])
    }


def describe_change(row) -> str:
    if row["extra_id"]:
        return "Дополнительный урок"
    if row["is_cancelled"]:
        return "Урока не будет"
    parts = []
    if row["sub_slot_id"]:
        parts.append(f"Перенос на {row['moved_number']} урок")
    if row["sub_teacher_id"]:
        parts.append(f"Учитель: {row['new_teacher']}")
    if row["sub_subject_id"]:
        parts.append(f"Предмет: {row['new_subject']}")
    if row["sub_room_id"]:
        parts.append(f"Кабинет: {row['new_room']}")
    return ", ".join(parts)


def change_flag(row) -> str | None:
    """Короткая пометка для карточки в сетке."""
    if row["extra_id"]:
        return "Доп. урок"
    if row["is_cancelled"]:
        return "Отмена"
    if row["sub_slot_id"]:
        return "Перенос"
    if row["sub_teacher_id"] or row["sub_subject_id"] or row["sub_room_id"]:
        return "Замена"
    return None


EXPORT_HEAD = ["Класс", "Урок", "По расписанию", "Учитель", "Кабинет", "Замена", "Примечание"]


def export_rows(rows) -> list[list]:
    return [
        [
            r["class_name"], r["lesson_number"], r["base_subject"], r["base_teacher"], r["base_room"] or "",
            describe_change(r), r["note"] or "",
        ]
        for r in rows if r["substitution_id"]
    ]
