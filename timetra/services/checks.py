from dataclasses import dataclass, field

from timetra.db.repo import Repo

CONFLICT = "conflict"
WARNING = "warning"


@dataclass
class PlacementCheck:
    room_busy: str | None = None  # запрет: сохранить такой урок нельзя
    conflicts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not (self.room_busy or self.conflicts or self.warnings)


@dataclass
class Problem:
    severity: str
    day: int
    slot: int
    title: str
    text: str
    fix: str
    lesson_ids: list[int]
    weeks: set[int] = field(default_factory=set)


def _overlap(a, b) -> bool:
    # весь класс (0) пересекается с любой подгруппой, разные подгруппы могут идти параллельно
    return a["class_id"] == b["class_id"] and (
        a["subgroup"] == b["subgroup"] or a["subgroup"] == 0 or b["subgroup"] == 0
    )


def _room_warnings(repo: Repo, wl, room) -> list[str]:
    out = []
    required = wl["required_room_type_id"]
    if required and room["room_type_id"] != required:
        type_name = next(t["name"] for t in repo.room_types() if t["id"] == required)
        out.append(f"Для предмета «{wl['subject_name']}» нужен кабинет типа «{type_name}»")
    students = wl["students_count"]
    if students and wl["subgroup"]:
        students = (students + 1) // 2  # точный размер подгруппы не хранится, считаем половину класса
    if room["capacity"] and students and room["capacity"] < students:
        out.append(f"В кабинете {room['number']} {room['capacity']} мест, а учеников {students}")
    return out


def check_placement(repo: Repo, version, wl, week, day, slot, room_id=None, skip_ids=()) -> PlacementCheck:
    result = PlacementCheck()
    target = {"class_id": wl["class_id"], "subgroup": wl["subgroup"]}
    for other in repo.lessons_at(version, week, day, slot, skip_ids):
        if room_id and other["classroom_id"] == room_id:
            result.room_busy = f"Кабинет {other['room_number']} занят: там урок {other['class_name']}"
        if other["teacher_id"] == wl["teacher_id"]:
            result.warnings.append(
                f"Учитель {wl['teacher_short']} в это время занят: {other['subject_name']} в {other['class_name']}"
            )
        if _overlap(target, other):
            result.conflicts.append(f"У класса {wl['class_name']} уже стоит {other['subject_name']}")
    if (day, slot) in repo.teacher_off(wl["teacher_id"]):
        result.warnings.append(f"Учитель {wl['teacher_short']} в это время не может вести уроки")
    if room_id:
        room = next(r for r in repo.rooms() if r["id"] == room_id)
        result.warnings.extend(_room_warnings(repo, wl, room))
    return result


def find_problems(repo: Repo, version) -> list[Problem]:
    """Одинаковые проблемы на обеих неделях склеиваются в одну запись."""
    found: dict[tuple, Problem] = {}

    def add(key, week, problem: Problem):
        if key in found:
            found[key].weeks.add(week)
        else:
            problem.weeks.add(week)
            found[key] = problem

    lessons = {row["id"]: row for row in repo.lessons(version)}
    workloads = {w["id"]: w for w in repo.workload(version)}
    rooms = {r["id"]: r for r in repo.rooms()}

    for pair in repo.conflict_pairs(version):
        a, b = lessons[pair["schedule_id_1"]], lessons[pair["schedule_id_2"]]
        key = (pair["conflict_type"], *sorted((a["workload_id"], b["workload_id"])), a["weekday_id"], a["lesson_slot_id"])
        names = f"{_lesson_name(a)} и {_lesson_name(b)}."
        ids = [a["id"], b["id"]]
        if pair["conflict_type"] == "teacher":
            problem = Problem(
                WARNING, a["weekday_id"], a["lesson_slot_id"], f"Учитель {a['teacher_short']} ведёт два урока сразу",
                names, "Перенесите один из уроков или поменяйте учителя в нагрузке.", ids,
            )
        else:
            problem = Problem(
                CONFLICT, a["weekday_id"], a["lesson_slot_id"], f"У класса {a['class_name']} два урока сразу",
                names, "Перенесите один из уроков.", ids,
            )
        add(key, a["week_type_id"], problem)

    offs: dict[int, set] = {}
    qualified: dict[int, set] = {}
    for row in lessons.values():
        wl = workloads[row["workload_id"]]
        teacher = row["teacher_id"]
        off = offs.setdefault(teacher, repo.teacher_off(teacher))
        day, slot = row["weekday_id"], row["lesson_slot_id"]
        if (day, slot) in off:
            add(
                ("off", row["workload_id"], day, slot), row["week_type_id"],
                Problem(
                    WARNING, day, slot, f"Учитель {row['teacher_short']} в это время не может вести уроки",
                    _lesson_name(row) + ".", "Перенесите урок на другое время.", [row["id"]],
                ),
            )
        if row["classroom_id"]:
            for text in _room_warnings(repo, wl, rooms[row["classroom_id"]]):
                add(
                    ("room", row["workload_id"], day, slot, text), row["week_type_id"],
                    Problem(
                        WARNING, day, slot, text, _lesson_name(row) + ".",
                        "Откройте урок и выберите другой кабинет.", [row["id"]],
                    ),
                )
        subjects = qualified.setdefault(teacher, repo.teacher_subject_ids(teacher))
        if row["subject_id"] not in subjects:
            add(
                ("subject", row["workload_id"]), row["week_type_id"],
                Problem(
                    WARNING, day, slot,
                    f"{row['teacher_short']} не отмечен как учитель предмета «{row['subject_name']}»",
                    row["class_name"] + ".", "Проверьте карточку учителя в разделе «Справочники».", [row["id"]],
                ),
            )

    per_day: dict[tuple, list] = {}
    for row in lessons.values():
        per_day.setdefault((row["class_id"], row["week_type_id"], row["weekday_id"]), []).append(row)
    for (class_id, week, day), rows in per_day.items():
        count = len({r["lesson_slot_id"] for r in rows})
        limit = repo.grade_limit(rows[0]["grade"])
        if limit and count > limit:
            add(
                ("limit", class_id, day), week,
                Problem(
                    WARNING, day, rows[0]["lesson_slot_id"],
                    f"У класса {rows[0]['class_name']} {count} уроков за день при лимите {limit}",
                    "", "Перенесите урок на другой день.", [rows[0]["id"]],
                ),
            )
    return sorted(found.values(), key=lambda p: (p.severity != CONFLICT, p.day, p.slot))


def _lesson_name(row) -> str:
    group = f" (гр. {row['subgroup']})" if row["subgroup"] else ""
    return f"{row['class_name']}, {row['subject_name']}{group}"


def day_score(lessons, class_id, week, day) -> int:
    """Параллельные подгруппы для класса один урок, поэтому берём максимум по слоту."""
    best: dict[int, int] = {}
    for row in lessons:
        if row["class_id"] == class_id and row["week_type_id"] == week and row["weekday_id"] == day:
            slot = row["lesson_slot_id"]
            best[slot] = max(best.get(slot, 0), row["score"])
    return sum(best.values())
