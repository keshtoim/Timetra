import math
from dataclasses import dataclass, field

from timetra.db.repo import Repo

ODD, EVEN = 1, 2
PEAK_EVEN, PEAK_TUE_WED, PEAK_WED_THU = "even", "tue_wed", "wed_thu"
PEAK_DAYS = {PEAK_EVEN: (), PEAK_TUE_WED: (2, 3), PEAK_WED_THU: (3, 4)}
PEAK_WEIGHT = 1.2  # во сколько раз пиковый день тяжелее обычного

# веса штрафов подобраны так, чтобы запреты по смыслу (повтор предмета) были дороже пожеланий (удобный номер урока)
COST_NO_ROOM = 200  # спортзал один: второй класс в это время останется без него
COST_REPEAT_SUBJECT = 100
COST_DAY_LOAD = 40
COST_BAD_SLOT = 30
COST_EXTRA_LESSON = 15
COST_HARD_NEIGHBOUR = 12
COST_HOLE = 8
COST_LATE_SLOT = 2


def best_slots(grade: int) -> range:
    """Номера уроков для самых трудных предметов: младшим раньше, старшим на 2-4 уроке."""
    if grade == 1:
        return range(2, 3)
    if grade <= 4:
        return range(2, 4)
    return range(2, 5)


@dataclass
class Report:
    placed: int = 0
    missing: list[str] = field(default_factory=list)
    no_scores: list[str] = field(default_factory=list)


@dataclass
class Unit:
    """Что ставится в один слот: урок или параллельные подгруппы, на одну или обе недели."""

    workloads: list
    both_weeks: bool
    score: int
    hard: bool = False
    weeks: tuple = ()
    day: int = 0
    slot: int = 0

    @property
    def first(self):
        return self.workloads[0]


def _choose_room(wl, rooms, busy) -> int | None:
    """Свой кабинет класса, если подходит и свободен, иначе первый подходящий. None, если такого нет."""
    required = wl["required_room_type_id"]
    students = wl["students_count"]
    if students and wl["subgroup"]:
        students = (students + 1) // 2
    candidates = sorted(rooms, key=lambda r: r["id"] != wl["home_classroom_id"])
    fallback = None
    for room in candidates:
        if room["id"] in busy:
            continue
        if required and room["room_type_id"] != required:
            continue
        # без требований к кабинету не занимаем спортзал или лабораторию, кроме своего кабинета класса
        if not required and room["id"] != wl["home_classroom_id"] and room["type_name"] != "Обычный":
            continue
        if room["capacity"] and students and room["capacity"] < students:
            fallback = fallback or room["id"]
            continue
        return room["id"]
    return fallback


def pick_room(repo: Repo, wl, version, weeks, day, slot) -> int | None:
    busy = {row["classroom_id"] for week in weeks for row in repo.lessons_at(version, week, day, slot)}
    return _choose_room(wl, repo.rooms(), busy)


class _Board:
    """Занятость в памяти: перебор вариантов через запросы к базе был бы слишком медленным."""

    def __init__(self, repo: Repo, version):
        self.teachers: dict[tuple, list] = {}
        self.classes: dict[tuple, list] = {}
        self.rooms_busy: dict[tuple, set] = {}
        self.required: dict[tuple, int] = {}
        self.day_units: dict[tuple, list] = {}
        self.off: dict[int, set] = {}
        self.repo = repo
        self.rooms = repo.rooms()
        self.type_count: dict[int, int] = {}
        for room in self.rooms:
            self.type_count[room["room_type_id"]] = self.type_count.get(room["room_type_id"], 0) + 1
        slots = repo.slots()
        self.overlap = {
            a["id"]: {
                b["id"] for b in slots
                if a["id"] == b["id"] or (
                    a["starts_at"] and a["ends_at"] and b["starts_at"] and b["ends_at"]
                    and a["starts_at"] < b["ends_at"] and b["starts_at"] < a["ends_at"]
                )
            }
            for a in slots
        }
        self.numbers = {s["id"]: s["number"] for s in slots}
        for row in repo.lessons(version):
            key = (row["week_type_id"], row["weekday_id"], row["lesson_slot_id"])
            self.teachers.setdefault(key, []).append(row["teacher_id"])
            self.classes.setdefault(key, []).append((row["class_id"], row["subgroup"]))
            if row["classroom_id"]:
                self.rooms_busy.setdefault(key, set()).add(row["classroom_id"])
            if row["required_room_type_id"]:
                type_key = (*key, row["required_room_type_id"])
                self.required[type_key] = self.required.get(type_key, 0) + 1
            self.day_units.setdefault((row["class_id"], row["week_type_id"], row["weekday_id"]), []).append(
                (row["lesson_slot_id"], row["score"], row["subject_id"], row["subgroup"])
            )

    def off_for(self, teacher_id):
        if teacher_id not in self.off:
            self.off[teacher_id] = self.repo.teacher_off(teacher_id)
        return self.off[teacher_id]

    def can_place(self, unit: Unit, weeks, day, slot) -> bool:
        for wl in unit.workloads:
            if (day, slot) in self.off_for(wl["teacher_id"]):
                return False
            for week in weeks:
                for other in self.overlap[slot]:
                    if wl["teacher_id"] in self.teachers.get((week, day, other), ()):
                        return False
                for class_id, subgroup in self.classes.get((week, day, slot), ()):
                    if class_id == wl["class_id"] and (subgroup == wl["subgroup"] or not subgroup or not wl["subgroup"]):
                        return False
        return True

    def special_room_free(self, unit: Unit, weeks, day, slot) -> bool:
        for wl in unit.workloads:
            required = wl["required_room_type_id"]
            if required and any(
                self.required.get((week, day, slot, required), 0) >= self.type_count.get(required, 0) for week in weeks
            ):
                return False
        return True

    def add(self, unit: Unit):
        for week in unit.weeks:
            key = (week, unit.day, unit.slot)
            for wl in unit.workloads:
                self.teachers.setdefault(key, []).append(wl["teacher_id"])
                self.classes.setdefault(key, []).append((wl["class_id"], wl["subgroup"]))
                if wl["required_room_type_id"]:
                    type_key = (*key, wl["required_room_type_id"])
                    self.required[type_key] = self.required.get(type_key, 0) + 1
                self.day_units.setdefault((wl["class_id"], week, unit.day), []).append(
                    (unit.slot, unit.score, wl["subject_id"], wl["subgroup"])
                )

    def remove(self, unit: Unit):
        for week in unit.weeks:
            key = (week, unit.day, unit.slot)
            for wl in unit.workloads:
                self.teachers[key].remove(wl["teacher_id"])
                self.classes[key].remove((wl["class_id"], wl["subgroup"]))
                if wl["required_room_type_id"]:
                    self.required[(*key, wl["required_room_type_id"])] -= 1
                self.day_units[(wl["class_id"], week, unit.day)].remove(
                    (unit.slot, unit.score, wl["subject_id"], wl["subgroup"])
                )

    def day_load(self, class_id, week, day) -> int:
        """Параллельные подгруппы для класса один урок, поэтому берём максимум по слоту."""
        best: dict[int, int] = {}
        for slot, score, _subject, _sub in self.day_units.get((class_id, week, day), ()):
            best[slot] = max(best.get(slot, 0), score)
        return sum(best.values())

    def used_slots(self, class_id, week, day) -> set[int]:
        return {x[0] for x in self.day_units.get((class_id, week, day), ())}


def _build_units(repo: Repo, version) -> tuple[list[Unit], list[str]]:
    workloads = repo.workload(version)
    scores: dict[tuple, int] = {}
    no_scores = set()
    for wl in workloads:
        table = scores.setdefault(("subject", wl["subject_id"]), repo.subject_scores(wl["subject_id"]))
        if not table.get(wl["grade"]):
            no_scores.add(wl["subject_name"])
    units: list[Unit] = []
    groups: dict[tuple, list] = {}
    for wl in workloads:
        groups.setdefault((wl["class_id"], wl["subject_id"]), []).append(wl)
    for (_class, subject), items in groups.items():
        score = scores[("subject", subject)].get(items[0]["grade"], 0)
        left = {w["id"]: w["lessons_per_fortnight"] - w["placed"] for w in items}
        parallel = [w for w in items if w["subgroup"]]
        # подгруппы ставим в один слот, иначе у остального класса получится окно
        if len(parallel) > 1 and len({w["teacher_id"] for w in parallel}) == len(parallel):
            while all(left[w["id"]] >= 2 for w in parallel):
                units.append(Unit(parallel, True, score))
                for w in parallel:
                    left[w["id"]] -= 2
            while all(left[w["id"]] >= 1 for w in parallel):
                units.append(Unit(parallel, False, score))
                for w in parallel:
                    left[w["id"]] -= 1
        for w in items:
            while left[w["id"]] >= 2:
                units.append(Unit([w], True, score))
                left[w["id"]] -= 2
            if left[w["id"]] == 1:
                units.append(Unit([w], False, score))
                left[w["id"]] = 0
    return units, sorted(no_scores)


def _mark_hard(units: list[Unit]) -> None:
    """Трудная в классе — верхняя треть уроков по баллам: сравниваем внутри класса, а не с общей границей."""
    by_class: dict[int, list[Unit]] = {}
    for unit in units:
        by_class.setdefault(unit.first["class_id"], []).append(unit)
    for items in by_class.values():
        ranked = sorted((u.score for u in items), reverse=True)
        border = ranked[len(ranked) // 3] if ranked else 0
        for unit in items:
            unit.hard = unit.score > 0 and unit.score >= border


class _Planner:
    def __init__(self, repo: Repo, board: _Board, units: list[Unit], peak: str):
        self.board = board
        self.slots_by_shift: dict[int, list] = {}
        self.limits: dict[int, int | None] = {}
        self.repo = repo
        self.peak = PEAK_DAYS[peak]
        self.targets: dict[tuple, float] = {}
        self.counts: dict[int, int] = {}
        per_class: dict[int, list[Unit]] = {}
        for unit in units:
            per_class.setdefault(unit.first["class_id"], []).append(unit)
        for class_id, items in per_class.items():
            days = range(1, items[0].first["study_days"] + 1)
            per_week = sum(u.score * (1 if u.both_weeks else 0.5) for u in items)
            per_week += sum(board.day_load(class_id, ODD, d) + board.day_load(class_id, EVEN, d) for d in days) / 2
            weights = {d: PEAK_WEIGHT if d in self.peak else 1.0 for d in days}
            total = sum(weights.values())
            for day in days:
                self.targets[(class_id, day)] = max(1.0, per_week * weights[day] / total)
            lessons = sum(1 if u.both_weeks else 0.5 for u in items)
            lessons += sum(len(board.used_slots(class_id, ODD, d)) for d in days)
            self.counts[class_id] = math.ceil(lessons / len(days))

    def slots_for(self, shift_id):
        if shift_id not in self.slots_by_shift:
            self.slots_by_shift[shift_id] = self.repo.slots(shift_id)
        return self.slots_by_shift[shift_id]

    def limit_for(self, grade, slots):
        if grade not in self.limits:
            self.limits[grade] = self.repo.grade_limit(grade)
        return self.limits[grade] or len(slots)

    def cost(self, unit: Unit, weeks, day, slot) -> float:
        board, wl = self.board, unit.first
        class_id = wl["class_id"]
        number = board.numbers[slot]
        week = weeks[0]
        used = board.used_slots(class_id, week, day)
        cost = COST_DAY_LOAD * (board.day_load(class_id, week, day) + unit.score) / self.targets[(class_id, day)]
        units_today = board.day_units.get((class_id, week, day), ())
        if any(x[2] == wl["subject_id"] and x[3] == wl["subgroup"] for x in units_today):
            cost += COST_REPEAT_SUBJECT
        if len(used) >= self.counts[class_id]:
            cost += COST_EXTRA_LESSON * (len(used) - self.counts[class_id] + 1)
        if unit.hard:
            good = best_slots(wl["grade"])
            if number not in good:
                cost += COST_BAD_SLOT + 5 * min(abs(number - good.start), abs(number - good.stop + 1))
            numbers_today = {board.numbers[x[0]]: x[1] for x in units_today}
            for neighbour in (number - 1, number + 1):
                if numbers_today.get(neighbour, 0) >= unit.score:
                    cost += COST_HARD_NEIGHBOUR
        else:
            holes = sum(1 for s in self.slots_for(wl["shift_id"]) if s["number"] < number and s["id"] not in used)
            cost += COST_HOLE * holes
        cost += COST_LATE_SLOT * number
        if not board.special_room_free(unit, weeks, day, slot):
            cost += COST_NO_ROOM
        return cost

    def place(self, unit: Unit) -> bool:
        wl = unit.first
        slots = self.slots_for(wl["shift_id"])
        limit = self.limit_for(wl["grade"], slots)
        options = [(ODD, EVEN)] if unit.both_weeks else [(ODD,), (EVEN,)]
        best = None
        for weeks in options:
            for day in range(1, wl["study_days"] + 1):
                for slot in slots:
                    # лимит считаем только для нового слота: параллельный урок дня не удлиняет
                    used = self.board.used_slots(wl["class_id"], weeks[0], day)
                    if slot["id"] not in used and len(used) >= limit:
                        continue
                    if not self.board.can_place(unit, weeks, day, slot["id"]):
                        continue
                    cost = self.cost(unit, weeks, day, slot["id"])
                    if best is None or cost < best[0]:
                        best = (cost, weeks, day, slot["id"])
        if best is None:
            return False
        _cost, unit.weeks, unit.day, unit.slot = best
        self.board.add(unit)
        return True

    def close_gaps(self, placed: list[Unit]) -> None:
        """Трудные предметы ставятся первыми и оставляют окна внизу дня, сдвигаем в них последние уроки."""
        for unit in sorted(placed, key=lambda u: -self.board.numbers[u.slot]):
            wl = unit.first
            used = set()
            for week in unit.weeks:
                used |= self.board.used_slots(wl["class_id"], week, unit.day)
            number = self.board.numbers[unit.slot]
            for slot in self.slots_for(wl["shift_id"]):
                if slot["number"] >= number or slot["id"] in used:
                    continue
                self.board.remove(unit)
                fits = self.board.can_place(unit, unit.weeks, unit.day, slot["id"]) and self.board.special_room_free(
                    unit, unit.weeks, unit.day, slot["id"]
                )
                if fits:
                    unit.slot = slot["id"]
                self.board.add(unit)
                if fits:
                    break
        self._swap_into_gaps(placed)

    def _swap_into_gaps(self, placed: list[Unit]) -> None:
        """Урок не сдвинуть в окно (например, спортзал занят): пробуем поменять его с другим уроком дня."""
        for unit in sorted(placed, key=lambda u: -self.board.numbers[u.slot]):
            wl = unit.first
            used = set()
            for week in unit.weeks:
                used |= self.board.used_slots(wl["class_id"], week, unit.day)
            number = self.board.numbers[unit.slot]
            holes = [s["id"] for s in self.slots_for(wl["shift_id"]) if s["number"] < number and s["id"] not in used]
            if not holes:
                continue
            # трудные уроки в последнюю очередь: их место на 2-4 уроке терять жаль
            others = [
                o for o in placed
                if o is not unit and o.day == unit.day and o.weeks == unit.weeks
                and o.first["class_id"] == wl["class_id"] and self.board.numbers[o.slot] < number
            ]
            for other in sorted(others, key=lambda o: o.hard):
                if self._try_swap(unit, other, holes[0]):
                    break

    def _try_swap(self, unit: Unit, other: Unit, hole: int) -> bool:
        board = self.board
        target = other.slot
        board.remove(unit)
        board.remove(other)
        fits = (
            board.can_place(other, other.weeks, other.day, hole)
            and board.special_room_free(other, other.weeks, other.day, hole)
            and board.can_place(unit, unit.weeks, unit.day, target)
            and board.special_room_free(unit, unit.weeks, unit.day, target)
        )
        if fits:
            other.slot, unit.slot = hole, target
        board.add(unit)
        board.add(other)
        return fits


def _assign_rooms(repo: Repo, board: _Board, units: list[Unit]) -> dict[tuple, int | None]:
    rooms: dict[tuple, int | None] = {}
    entries = [(unit, wl) for unit in units for wl in unit.workloads]
    # сначала уроки с особым кабинетом: обычных кабинетов больше, они найдутся и потом
    entries.sort(key=lambda e: e[1]["required_room_type_id"] is None)
    for unit, wl in entries:
        busy = set()
        for week in unit.weeks:
            for other in board.overlap[unit.slot]:
                busy |= board.rooms_busy.get((week, unit.day, other), set())
        room = _choose_room(wl, board.rooms, busy)
        rooms[(id(unit), wl["id"])] = room
        if room:
            for week in unit.weeks:
                board.rooms_busy.setdefault((week, unit.day, unit.slot), set()).add(room)
    return rooms


def auto_place(repo: Repo, version, peak: str = PEAK_EVEN) -> Report:
    """Костяк расписания по баллам сложности. Существующие уроки не трогает, транзакцию открывает вызывающий код.

    Жадный алгоритм: уроки идут от самых трудных к простым, каждый ставится в самое дешёвое по штрафам место.
    """
    units, no_scores = _build_units(repo, version)
    report = Report(no_scores=no_scores)
    if not units:
        return report
    _mark_hard(units)
    board = _Board(repo, version)
    planner = _Planner(repo, board, units, peak)
    busy_teacher: dict[int, int] = {}
    for unit in units:
        for wl in unit.workloads:
            busy_teacher[wl["teacher_id"]] = busy_teacher.get(wl["teacher_id"], 0) + 1
    order = sorted(
        units,
        key=lambda u: (not u.hard, -u.score, -max(busy_teacher[w["teacher_id"]] for w in u.workloads), u.first["class_name"]),
    )
    placed = []
    for unit in order:
        if planner.place(unit):
            placed.append(unit)
        else:
            for wl in unit.workloads:
                group = f" (гр. {wl['subgroup']})" if wl["subgroup"] else ""
                report.missing.append(f"{wl['class_name']}, {wl['subject_name']}{group}")
    planner.close_gaps(placed)
    rooms = _assign_rooms(repo, board, placed)
    for unit in placed:
        for wl in unit.workloads:
            for week in unit.weeks:
                repo.add_lesson(version, wl["id"], week, unit.day, unit.slot, rooms[(id(unit), wl["id"])])
                report.placed += 1
    return report
