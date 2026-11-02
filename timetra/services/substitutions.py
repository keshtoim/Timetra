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
    if date.isoweekday() == SUNDAY:
        return []
    return repo.lessons_on_date(version, week_for_date(date, offset), date.isoweekday(), date.isoformat())


def check_substitution(repo: Repo, version, date, offset, lesson, teacher_id, subject_id, room_id) -> SubstitutionCheck:
    """Смотрим на день с учётом других замен, а не на расписание: учитель мог уже кого-то заменять."""
    result = SubstitutionCheck()
    week = week_for_date(date, offset)
    slot = lesson["lesson_slot_id"]
    together = {x["id"] for x in repo.lessons_at(version, week, date.isoweekday(), slot)}
    teachers = {t["id"]: t["short"] for t in repo.teachers()}
    subjects = {s["id"]: s["name"] for s in repo.subjects()}
    for other in day_lessons(repo, version, date, offset):
        if other["lesson_id"] == lesson["lesson_id"] or other["lesson_id"] not in together or other["is_cancelled"]:
            continue
        if room_id and other["eff_room_id"] == room_id:
            number = next(r["number"] for r in repo.rooms() if r["id"] == room_id)
            result.room_busy = f"Кабинет {number} занят: там урок {other['class_name']}"
        if other["eff_teacher_id"] == teacher_id:
            result.warnings.append(f"Учитель {teachers[teacher_id]} в это время ведёт урок в {other['class_name']}")
    if (date.isoweekday(), slot) in repo.teacher_off(teacher_id):
        result.warnings.append(f"Учитель {teachers[teacher_id]} в это время не может вести уроки")
    taught = repo.teacher_subject_ids(teacher_id)
    if taught and subject_id not in taught:
        result.warnings.append(f"{teachers[teacher_id]} не отмечен как учитель предмета «{subjects[subject_id]}»")
    return result


def free_teacher_ids(repo: Repo, version, date, offset, lesson) -> set[int]:
    """Кто свободен на этом уроке: для подсказок в списке учителей."""
    week = week_for_date(date, offset)
    slot = lesson["lesson_slot_id"]
    together = {x["id"] for x in repo.lessons_at(version, week, date.isoweekday(), slot)}
    busy = {
        x["eff_teacher_id"] for x in day_lessons(repo, version, date, offset)
        if x["lesson_id"] in together and not x["is_cancelled"] and x["lesson_id"] != lesson["lesson_id"]
    }
    return {
        t["id"] for t in repo.teachers()
        if t["id"] not in busy and (date.isoweekday(), slot) not in repo.teacher_off(t["id"])
    }


def describe_change(row) -> str:
    if row["is_cancelled"]:
        return "Урока не будет"
    parts = []
    if row["sub_teacher_id"]:
        parts.append(f"Учитель: {row['new_teacher']}")
    if row["sub_subject_id"]:
        parts.append(f"Предмет: {row['new_subject']}")
    if row["sub_room_id"]:
        parts.append(f"Кабинет: {row['new_room']}")
    return ", ".join(parts)


EXPORT_HEAD = ["Класс", "Урок", "По расписанию", "Учитель", "Кабинет", "Замена", "Примечание"]


def export_rows(rows) -> list[list]:
    return [
        [
            r["class_name"], r["lesson_number"], r["base_subject"], r["base_teacher"], r["base_room"] or "",
            describe_change(r), r["note"] or "",
        ]
        for r in rows if r["substitution_id"]
    ]
