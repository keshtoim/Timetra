import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from timetra.db.repo import Repo
from timetra.io.tables import TableError

CLASS_RE = re.compile(r"^(\d{1,2})\s*-?\s*(\S.*)$")
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})")
GRADES = range(1, 12)
ODD, EVEN = 1, 2

ADD, SKIP, ERROR = "add", "skip", "error"
# порядок листов совпадает с зависимостями: учителям нужны предметы, классам кабинеты и так далее
BOOK_ORDER = ("rooms", "subjects", "teachers", "classes", "slots", "workload", "schedule")


class RowError(Exception):
    pass


class RowSkip(Exception):
    pass


@dataclass
class Column:
    title: str
    required: bool
    hint: str
    example: str = ""


@dataclass
class RowResult:
    values: list[str]
    status: str
    message: str
    apply: Callable | None = None


def _int(text, name, low=None, high=None):
    try:
        number = int(float(text.replace(",", ".")))
    except ValueError as error:
        raise RowError(f"«{name}»: нужно число") from error
    if (low is not None and number < low) or (high is not None and number > high):
        raise RowError(f"«{name}»: число должно быть от {low} до {high}")
    return number


def _optional_int(text, name, low=None, high=None):
    return _int(text, name, low, high) if text else None


def _time(text, name):
    if not text:
        return ""
    match = TIME_RE.match(text)
    if not match or int(match[1]) > 23 or int(match[2]) > 59:
        raise RowError(f"«{name}»: укажите время, например 08:30")
    return f"{int(match[1]):02d}:{match[2]}"


def _norm(text):
    return text.strip().lower().replace("ё", "е")


class Lookups:
    """Справочники для сверки с файлом. Обновляются строками, уже разобранными в этом файле."""

    def __init__(self, repo: Repo):
        self.repo = repo
        self.classes = {x["name"].lower().replace(" ", ""): x for x in repo.classes()}
        self.subjects = {_norm(s["name"]): s["id"] for s in repo.subjects()}
        for s in repo.subjects():
            if s["short_name"]:
                self.subjects.setdefault(_norm(s["short_name"]), s["id"])
        self.rooms = {r["number"].lower(): r["id"] for r in repo.rooms()}
        self.room_types = {_norm(t["name"]): t["id"] for t in repo.room_types()}
        self.days = {_norm(d["name"]): d["id"] for d in repo.weekdays()}
        self.teachers: dict[str, list[int]] = {}
        for t in repo.teachers():
            for key in (t["full_name"], t["short"]):
                self.teachers.setdefault(_norm(key), []).append(t["id"])
            self.teachers.setdefault(_norm(t["last_name"]), []).append(t["id"])
        self.seen: set = set()

    def class_of(self, text):
        row = self.classes.get(text.lower().replace(" ", "").replace("-", ""))
        if not row:
            raise RowError(f"Класса «{text}» нет в справочнике")
        return row

    def subject(self, text):
        found = self.subjects.get(_norm(text))
        if not found:
            raise RowError(f"Предмета «{text}» нет в справочнике")
        return found

    def teacher(self, text):
        found = self.teachers.get(_norm(text))
        if not found:
            raise RowError(f"Учителя «{text}» нет в справочнике")
        if len(set(found)) > 1:
            raise RowError(f"Учителей «{text}» несколько, укажите полное ФИО")
        return found[0]

    def room(self, text):
        found = self.rooms.get(text.lower())
        if not found:
            raise RowError(f"Кабинета «{text}» нет в справочнике")
        return found

    def room_type(self, text):
        if not text:
            return None
        found = self.room_types.get(_norm(text))
        if not found:
            names = ", ".join(t["name"] for t in self.repo.room_types())
            raise RowError(f"Неизвестный тип кабинета «{text}». Подходят: {names}")
        return found

    def once(self, key):
        if key in self.seen:
            raise RowSkip("Такая строка в файле уже была")
        self.seen.add(key)


def _parse_teacher(row, lk: Lookups):
    last, first, pat = row["Фамилия"], row["Имя"], row["Отчество"]
    full = _norm(" ".join(x for x in (last, first, pat) if x))
    lk.once(full)
    if full in lk.teachers:
        raise RowSkip("Уже есть в базе")
    ids = [lk.subject(x) for x in re.split(r"[,;]", row["Предметы"]) if x.strip()]
    return lambda repo: repo.save_teacher(None, last, first, pat, ids)


def _parse_class(row, lk: Lookups):
    match = CLASS_RE.match(row["Класс"])
    if not match or not 1 <= int(match[1]) <= 11:
        raise RowError("«Класс»: укажите параллель и букву, например 5А")
    grade, letter = int(match[1]), match[2].strip().upper()
    key = f"{grade}{letter}".lower()
    lk.once(key)
    if key in lk.classes:
        raise RowSkip("Уже есть в базе")
    shift = _int(row["Смена"], "Смена", 1, 2) if row["Смена"] else 1
    days = _int(row["Учебных дней"], "Учебных дней", 5, 6) if row["Учебных дней"] else 5
    students = _optional_int(row["Учеников"], "Учеников", 1)
    room = lk.room(row["Кабинет"]) if row["Кабинет"] else None
    return lambda repo: repo.save_class(None, grade, letter, shift, days, students, None, room)


def _parse_subject(row, lk: Lookups):
    name = row["Название"]
    lk.once(_norm(name))
    if _norm(name) in lk.subjects:
        raise RowSkip("Уже есть в базе")
    scores = {g: _optional_int(row[f"Балл {g}"], f"Балл {g}", 1) for g in GRADES}
    room_type = lk.room_type(row["Тип кабинета"])
    return lambda repo: repo.save_subject(None, name, row["Короткое название"], room_type, scores)


def _parse_room(row, lk: Lookups):
    number = row["Номер"]
    lk.once(number.lower())
    if number.lower() in lk.rooms:
        raise RowSkip("Уже есть в базе")
    capacity = _optional_int(row["Мест"], "Мест", 1)
    room_type = lk.room_type(row["Тип"]) or 1
    return lambda repo: repo.save_room(None, number, capacity, room_type)


def _parse_slot(row, lk: Lookups):
    shift = _int(row["Смена"], "Смена", 1, 2) if row["Смена"] else 1
    number = _int(row["Номер урока"], "Номер урока", 1)
    start, end = _time(row["Начало"], "Начало"), _time(row["Конец"], "Конец")
    if start and end and start >= end:
        raise RowError("Конец урока должен быть позже начала")
    lk.once((shift, number))
    existing = next((s for s in lk.repo.slots(shift) if s["number"] == number), None)
    slot_id = existing["id"] if existing else None
    # номера уроков создаются при первом запуске, поэтому в файле важно именно время
    return lambda repo: repo.save_slot(slot_id, shift, number, start, end)


def _parse_workload(row, lk: Lookups):
    cls = lk.class_of(row["Класс"])
    subject = lk.subject(row["Предмет"])
    group = _int(row["Группа"], "Группа", 0) if row["Группа"] else 0
    teacher = lk.teacher(row["Учитель"])
    lessons = _int(row["Уроков за 2 недели"], "Уроков за 2 недели", 1)
    lk.once((cls["id"], subject, group))
    if any(w["subject_id"] == subject and w["subgroup"] == group for w in lk.repo.workload(0, cls["id"])):
        raise RowSkip("Уже есть в базе")
    return lambda repo: repo.save_workload(None, cls["id"], subject, group, teacher, lessons)


def _parse_lesson(row, lk: Lookups, version):
    weeks = {"нечетная": (ODD,), "четная": (EVEN,), "обе": (ODD, EVEN)}.get(_norm(row["Неделя"]))
    if not weeks:
        raise RowError("«Неделя»: укажите Нечётная, Чётная или Обе")
    day = lk.days.get(_norm(row["День"]))
    if not day:
        raise RowError(f"Неизвестный день «{row['День']}»")
    cls = lk.class_of(row["Класс"])
    number = _int(row["Номер урока"], "Номер урока", 1)
    slot = next((s for s in lk.repo.slots(cls["shift_id"]) if s["number"] == number), None)
    if not slot:
        raise RowError(f"В смене этого класса нет {number}-го урока. Добавьте его в разделе «Звонки»")
    subject = lk.subject(row["Предмет"])
    group = _int(row["Группа"], "Группа", 0) if row["Группа"] else 0
    workload = next(
        (w for w in lk.repo.workload(version, cls["id"]) if w["subject_id"] == subject and w["subgroup"] == group), None
    )
    if not workload:
        raise RowError("Такого урока нет в разделе «Нагрузка». Сначала добавьте его туда")
    room = lk.room(row["Кабинет"]) if row["Кабинет"] else None
    existing = {
        (x["week_type_id"], x["weekday_id"], x["lesson_slot_id"])
        for x in lk.repo.lessons(version) if x["workload_id"] == workload["id"]
    }
    new_weeks = [week for week in weeks if (week, day, slot["id"]) not in existing]
    if not new_weeks:
        raise RowSkip("Уже есть в расписании")
    for week in new_weeks:
        lk.once(("lesson", workload["id"], week, day, slot["id"]))
        if room:
            taken = lk.repo.lessons_at(version, week, day, slot["id"])
            if any(x["classroom_id"] == room for x in taken) or ("room", room, week, day, slot["id"]) in lk.seen:
                raise RowError(f"Кабинет {row['Кабинет']} занят на этом уроке")
            lk.seen.add(("room", room, week, day, slot["id"]))

    def apply(repo):
        for week in new_weeks:
            repo.add_lesson(version, workload["id"], week, day, slot["id"], room)

    return apply


@dataclass
class Kind:
    key: str
    title: str
    columns: list[Column]
    parse: Callable
    export: Callable


def _export_teachers(repo, _version):
    subjects = {s["id"]: s["name"] for s in repo.subjects()}
    return [
        [t["last_name"], t["first_name"], t["patronymic"] or "", ", ".join(sorted(subjects[s] for s in repo.teacher_subject_ids(t["id"])))]
        for t in repo.teachers()
    ]


def _export_classes(repo, _version):
    return [[x["name"], x["shift_id"], x["study_days"], x["students_count"] or "", x["room_number"] or ""] for x in repo.classes()]


def _export_subjects(repo, _version):
    rows = []
    for s in repo.subjects():
        scores = repo.subject_scores(s["id"])
        rows.append([s["name"], s["short_name"] or "", s["room_type_name"] or "", *[scores.get(g, "") for g in GRADES]])
    return rows


def _export_rooms(repo, _version):
    return [[r["number"], r["type_name"], r["capacity"] or ""] for r in repo.rooms()]


def _export_slots(repo, _version):
    return [[s["shift_id"], s["number"], s["starts_at"] or "", s["ends_at"] or ""] for s in repo.slots()]


def _export_workload(repo, version):
    teachers = {t["id"]: t["full_name"] for t in repo.teachers()}
    return [
        [w["class_name"], w["subject_name"], w["subgroup"], teachers[w["teacher_id"]], w["lessons_per_fortnight"]]
        for w in repo.workload(version)
    ]


def _export_schedule(repo, version):
    days = {d["id"]: d["name"] for d in repo.weekdays()}
    lessons = sorted(
        repo.lessons(version),
        key=lambda x: (x["class_name"], x["weekday_id"], x["lesson_number"], x["subgroup"], x["week_type_id"]),
    )
    rows, used = [], set()
    by_key = {(x["workload_id"], x["weekday_id"], x["lesson_slot_id"], x["week_type_id"]): x for x in lessons}
    for x in lessons:
        if x["id"] in used:
            continue
        twin = by_key.get((x["workload_id"], x["weekday_id"], x["lesson_slot_id"], EVEN if x["week_type_id"] == ODD else ODD))
        # урок на обеих неделях пишем одной строкой, если кабинет совпадает
        if twin and twin["classroom_id"] == x["classroom_id"]:
            used.add(twin["id"])
            week = "Обе"
        else:
            week = "Нечётная" if x["week_type_id"] == ODD else "Чётная"
        rows.append([
            week, days[x["weekday_id"]], x["lesson_number"], x["class_name"], x["subject_name"], x["subgroup"],
            x["teacher_short"], x["room_number"] or "",
        ])
    return rows


KINDS = [
    Kind(
        "teachers", "Учителя",
        [
            Column("Фамилия", True, "Фамилия учителя", "Иванова"),
            Column("Имя", True, "Имя учителя", "Мария"),
            Column("Отчество", False, "Можно оставить пустым", "Сергеевна"),
            Column("Предметы", False, "Через запятую. Предметы должны быть в справочнике", "Математика, Информатика"),
        ],
        _parse_teacher, _export_teachers,
    ),
    Kind(
        "classes", "Классы",
        [
            Column("Класс", True, "Параллель и буква", "5А"),
            Column("Смена", False, "1 или 2. Если пусто, то 1", "1"),
            Column("Учебных дней", False, "5 или 6. Если пусто, то 5", "5"),
            Column("Учеников", False, "Число учеников в классе", "26"),
            Column("Кабинет", False, "Закреплённый кабинет, должен быть в справочнике", "101"),
        ],
        _parse_class, _export_classes,
    ),
    Kind(
        "subjects", "Предметы",
        [
            Column("Название", True, "Полное название", "Математика"),
            Column("Короткое название", False, "Для клетки расписания", "Матем."),
            Column("Тип кабинета", False, "Обычный, Компьютерный класс, Спортзал или Лаборатория. Если нужен любой, оставьте пустым", ""),
            *[Column(f"Балл {g}", False, f"Балл сложности по СанПиН для {g} класса", "10" if g == 5 else "") for g in GRADES],
        ],
        _parse_subject, _export_subjects,
    ),
    Kind(
        "rooms", "Кабинеты",
        [
            Column("Номер", True, "Номер или название", "101"),
            Column("Тип", False, "Обычный, Компьютерный класс, Спортзал или Лаборатория. Если пусто, то Обычный", "Обычный"),
            Column("Мест", False, "Сколько учеников помещается", "30"),
        ],
        _parse_room, _export_rooms,
    ),
    Kind(
        "slots", "Звонки",
        [
            Column("Смена", False, "1 или 2. Если пусто, то 1", "1"),
            Column("Номер урока", True, "Номер урока в смене", "1"),
            Column("Начало", False, "Время начала", "08:30"),
            Column("Конец", False, "Время окончания", "09:15"),
        ],
        _parse_slot, _export_slots,
    ),
    Kind(
        "workload", "Нагрузка",
        [
            Column("Класс", True, "Класс из справочника", "5А"),
            Column("Предмет", True, "Предмет из справочника", "Математика"),
            Column("Группа", False, "0 или пусто — весь класс, 1, 2 — подгруппы", "0"),
            Column("Учитель", True, "Фамилия И. О. или полное ФИО", "Иванова М. С."),
            Column("Уроков за 2 недели", True, "5 уроков в неделю = 10", "10"),
        ],
        _parse_workload, _export_workload,
    ),
    Kind(
        "schedule", "Расписание",
        [
            Column("Неделя", True, "Нечётная, Чётная или Обе", "Обе"),
            Column("День", True, "Название дня", "Понедельник"),
            Column("Номер урока", True, "Номер урока в смене класса", "1"),
            Column("Класс", True, "Класс из справочника", "5А"),
            Column("Предмет", True, "Предмет из нагрузки класса", "Математика"),
            Column("Группа", False, "0 или пусто — весь класс, 1, 2 — подгруппы", "0"),
            Column("Учитель", False, "При загрузке не используется: учитель берётся из нагрузки", "Иванова М. С."),
            Column("Кабинет", False, "Кабинет из справочника", "101"),
        ],
        _parse_lesson, _export_schedule,
    ),
]


def kind_by_key(key: str) -> Kind:
    return next(k for k in KINDS if k.key == key)


def book_kinds() -> list[Kind]:
    return [kind_by_key(key) for key in BOOK_ORDER]


def export_table(repo: Repo, kind: Kind, version) -> tuple[list[str], list[list]]:
    return [col.title for col in kind.columns], kind.export(repo, version)


def template_help(kind: Kind) -> list[list[str]]:
    rows = [["Столбец", "Обязательный", "Что писать", "Пример"]]
    for col in kind.columns:
        rows.append([col.title, "да" if col.required else "нет", col.hint, col.example])
    return rows


def parse_rows(repo: Repo, kind: Kind, table: list[list[str]], version) -> list[RowResult]:
    if not table:
        raise TableError("В файле нет данных.")
    head = [cell.strip().lower() for cell in table[0]]
    positions = {}
    for col in kind.columns:
        if col.title.lower() in head:
            positions[col.title] = head.index(col.title.lower())
        elif col.required:
            raise TableError(f"В файле нет столбца «{col.title}». Скачайте шаблон и заполните его.")
    lookups = Lookups(repo)
    results = []
    for raw in table[1:]:
        row = {
            col.title: raw[positions[col.title]].strip()
            if col.title in positions and positions[col.title] < len(raw) else ""
            for col in kind.columns
        }
        values = [row[col.title] for col in kind.columns]
        missing = next((col.title for col in kind.columns if col.required and not row[col.title]), None)
        if missing:
            results.append(RowResult(values, ERROR, f"Не заполнено: {missing}"))
            continue
        try:
            action = kind.parse(row, lookups, version) if kind.key == "schedule" else kind.parse(row, lookups)
            results.append(RowResult(values, ADD, "Будет добавлено", action))
        except RowSkip as skip:
            results.append(RowResult(values, SKIP, str(skip)))
        except RowError as error:
            results.append(RowResult(values, ERROR, str(error)))
    return results


def apply_rows(repo: Repo, results: list[RowResult]) -> int:
    """Транзакцию открывает вызывающий код."""
    actions = [r.apply for r in results if r.status == ADD]
    for action in actions:
        action(repo)
    return len(actions)


def export_workbook(repo: Repo, version) -> list[tuple[str, list[str], list[list]]]:
    return [(kind.title, *export_table(repo, kind, version)) for kind in book_kinds()]


def template_workbook() -> list[tuple[str, list[str], list[list]]]:
    return [(kind.title, [col.title for col in kind.columns], []) for kind in book_kinds()]


def workbook_help() -> list[list[str]]:
    rows = [["Лист", "Столбец", "Обязательный", "Что писать", "Пример"]]
    for kind in book_kinds():
        rows.extend([kind.title, *row] for row in template_help(kind)[1:])
    return rows


def import_workbook(repo: Repo, sheets: dict[str, list[list[str]]], version) -> list[tuple[Kind, list[RowResult]]]:
    """Разбирает и сразу применяет листы по порядку: нагрузке нужны учителя с предыдущего листа.

    Транзакцию открывает вызывающий код.
    """
    found = [kind for kind in book_kinds() if kind.title.lower() in sheets]
    if not found:
        names = ", ".join(kind.title for kind in book_kinds())
        raise TableError(f"В файле нет нужных листов. Листы должны называться так: {names}.")
    done = []
    for kind in found:
        table = sheets[kind.title.lower()]
        if not table:
            continue
        try:
            results = parse_rows(repo, kind, table, version)
        except TableError as error:
            raise TableError(f"Лист «{kind.title}». {error}") from error
        apply_rows(repo, results)
        done.append((kind, results))
    return done


def preview_workbook(repo: Repo, sheets: dict[str, list[list[str]]], version) -> list[tuple[Kind, list[RowResult]]]:
    """Пробная загрузка с откатом: иначе строки, зависящие от предыдущих листов, выглядели бы ошибками."""
    try:
        return import_workbook(repo, sheets, version)
    except sqlite3.IntegrityError as error:
        raise TableError("Данные в файле противоречат друг другу. Проверьте повторяющиеся строки.") from error
    finally:
        repo.conn.rollback()
