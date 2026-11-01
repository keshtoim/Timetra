from timetra.db.repo import Repo

ODD, EVEN = 1, 2


def pick_room(repo: Repo, wl, version, weeks, day, slot) -> int | None:
    """Свой кабинет класса, если подходит и свободен, иначе первый подходящий. None, если такого нет."""
    required = wl["required_room_type_id"]
    busy = {
        row["classroom_id"]
        for week in weeks
        for row in repo.lessons_at(version, week, day, slot)
    }
    rooms = repo.rooms()
    rooms.sort(key=lambda r: r["id"] != wl["home_classroom_id"])
    for room in rooms:
        if room["id"] in busy:
            continue
        if required and room["room_type_id"] != required:
            continue
        # без требований к кабинету не занимаем спортзал или лабораторию, кроме своего кабинета класса
        if not required and room["id"] != wl["home_classroom_id"] and room["type_name"] != "Обычный":
            continue
        return room["id"]
    return None


def _can_place(repo: Repo, wl, version, weeks, day, slot, off) -> bool:
    if (day, slot) in off:
        return False
    for week in weeks:
        for other in repo.lessons_at(version, week, day, slot):
            if other["teacher_id"] == wl["teacher_id"]:
                return False
            if other["class_id"] == wl["class_id"] and (
                other["subgroup"] == wl["subgroup"] or not other["subgroup"] or not wl["subgroup"]
            ):
                return False
    return True


def auto_place(repo: Repo, version, class_id=None) -> int:
    """Простой жадный алгоритм: ставит уроки только туда, где нет накладок. Транзакцию открывает вызывающий код."""
    placed = 0
    for wl in repo.workload(version, class_id):
        slots = repo.slots(wl["shift_id"])
        limit = repo.grade_limit(wl["grade"]) or len(slots)
        off = repo.teacher_off(wl["teacher_id"])
        remaining = wl["lessons_per_fortnight"] - wl["placed"]
        while remaining > 0:
            weeks = (ODD, EVEN) if remaining >= 2 else (ODD,)
            spot = _find_spot(repo, wl, version, weeks, slots, limit, off)
            if not spot:
                break
            day, slot = spot
            room = pick_room(repo, wl, version, weeks, day, slot)
            for week in weeks:
                repo.add_lesson(version, wl["id"], week, day, slot, room)
            remaining -= len(weeks)
            placed += len(weeks)
    return placed


def _find_spot(repo: Repo, wl, version, weeks, slots, limit, off):
    lessons = [r for r in repo.lessons(version, weeks[0]) if r["class_id"] == wl["class_id"]]
    days = range(1, wl["study_days"] + 1)
    count = {d: len({r["lesson_slot_id"] for r in lessons if r["weekday_id"] == d}) for d in days}
    same_subject = {
        r["weekday_id"] for r in lessons if r["subject_id"] == wl["subject_id"] and r["subgroup"] == wl["subgroup"]
    }
    # первым проходом не ставим один предмет дважды в день
    for allow_repeat in (False, True):
        for day in sorted(days, key=lambda d: (count[d], d)):
            if count[day] >= limit or (day in same_subject and not allow_repeat):
                continue
            for slot in slots:
                if _can_place(repo, wl, version, weeks, day, slot["id"], off):
                    return day, slot["id"]
    return None
