import sqlite3
from collections.abc import Iterable

DEFAULT_LESSONS_COUNT = 7
FIRST_SHIFT = 1

TEACHER_SHORT = (
    "t.last_name || ' ' || substr(t.first_name, 1, 1) || '.' "
    "|| COALESCE(' ' || substr(t.patronymic, 1, 1) || '.', '')"
)


def _blank_to_none(value):
    return None if value == "" else value


class Repo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def _all(self, sql: str, *params) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def _one(self, sql: str, *params) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def snapshot(self) -> bytes:
        return self.conn.serialize()

    def restore(self, data: bytes) -> None:
        self.conn.deserialize(data)
        self.conn.execute("PRAGMA foreign_keys = ON")

    def ensure_defaults(self) -> None:
        """Без варианта и номеров уроков сетку не построить, поэтому создаём их при первом запуске."""
        with self.conn:
            if not self._one("SELECT 1 FROM schedule_versions"):
                self.conn.execute("INSERT INTO schedule_versions (name, is_active) VALUES ('Основной вариант', 1)")
            if not self._one("SELECT 1 FROM lesson_slots"):
                self.conn.executemany(
                    "INSERT INTO lesson_slots (shift_id, number) VALUES (?, ?)",
                    [(FIRST_SHIFT, n) for n in range(1, DEFAULT_LESSONS_COUNT + 1)],
                )

    def room_types(self):
        return self._all("SELECT * FROM room_types ORDER BY id")

    def shifts(self):
        return self._all("SELECT * FROM shifts ORDER BY id")

    def weekdays(self):
        return self._all("SELECT * FROM weekdays ORDER BY id")

    def week_types(self):
        return self._all("SELECT * FROM week_types ORDER BY id")

    def rooms(self):
        return self._all(
            """SELECT r.*, rt.name AS type_name FROM classrooms r
            JOIN room_types rt ON rt.id = r.room_type_id
            ORDER BY r.number"""
        )

    def save_room(self, room_id, number, capacity, room_type_id) -> None:
        if room_id:
            self.conn.execute(
                "UPDATE classrooms SET number = ?, capacity = ?, room_type_id = ? WHERE id = ?",
                (number, capacity, room_type_id, room_id),
            )
        else:
            self.conn.execute(
                "INSERT INTO classrooms (number, capacity, room_type_id) VALUES (?, ?, ?)",
                (number, capacity, room_type_id),
            )

    def delete_room(self, room_id) -> None:
        self.conn.execute("DELETE FROM classrooms WHERE id = ?", (room_id,))

    def slots(self, shift_id=None):
        sql = "SELECT * FROM lesson_slots"
        if shift_id:
            return self._all(sql + " WHERE shift_id = ? ORDER BY number", shift_id)
        return self._all(sql + " ORDER BY shift_id, number")

    def save_slot(self, slot_id, shift_id, number, starts_at, ends_at) -> None:
        starts_at, ends_at = _blank_to_none(starts_at), _blank_to_none(ends_at)
        if slot_id:
            self.conn.execute(
                "UPDATE lesson_slots SET shift_id = ?, number = ?, starts_at = ?, ends_at = ? WHERE id = ?",
                (shift_id, number, starts_at, ends_at, slot_id),
            )
        else:
            self.conn.execute(
                "INSERT INTO lesson_slots (shift_id, number, starts_at, ends_at) VALUES (?, ?, ?, ?)",
                (shift_id, number, starts_at, ends_at),
            )

    def delete_slot(self, slot_id) -> None:
        self.conn.execute("DELETE FROM lesson_slots WHERE id = ?", (slot_id,))

    def slot_in_use(self, slot_id) -> bool:
        return bool(self._one("SELECT 1 FROM schedule WHERE lesson_slot_id = ?", slot_id))

    def teachers(self):
        return self._all(
            f"""SELECT t.*, {TEACHER_SHORT} AS short,
                t.last_name || ' ' || t.first_name || COALESCE(' ' || t.patronymic, '') AS full_name
            FROM teachers t ORDER BY t.last_name, t.first_name"""
        )

    def teacher_subject_ids(self, teacher_id) -> set[int]:
        rows = self._all("SELECT subject_id FROM teacher_subjects WHERE teacher_id = ?", teacher_id)
        return {r["subject_id"] for r in rows}

    def teacher_off(self, teacher_id) -> set[tuple[int, int]]:
        rows = self._all(
            "SELECT weekday_id, lesson_slot_id FROM teacher_unavailability WHERE teacher_id = ?", teacher_id
        )
        return {(r["weekday_id"], r["lesson_slot_id"]) for r in rows}

    def save_teacher(self, teacher_id, last_name, first_name, patronymic, subject_ids=(), off=()) -> int:
        patronymic = _blank_to_none(patronymic)
        if teacher_id:
            self.conn.execute(
                "UPDATE teachers SET last_name = ?, first_name = ?, patronymic = ? WHERE id = ?",
                (last_name, first_name, patronymic, teacher_id),
            )
        else:
            teacher_id = self.conn.execute(
                "INSERT INTO teachers (last_name, first_name, patronymic) VALUES (?, ?, ?)",
                (last_name, first_name, patronymic),
            ).lastrowid
        self.conn.execute("DELETE FROM teacher_subjects WHERE teacher_id = ?", (teacher_id,))
        self.conn.executemany(
            "INSERT INTO teacher_subjects (teacher_id, subject_id) VALUES (?, ?)",
            [(teacher_id, s) for s in subject_ids],
        )
        self.conn.execute("DELETE FROM teacher_unavailability WHERE teacher_id = ?", (teacher_id,))
        self.conn.executemany(
            "INSERT INTO teacher_unavailability (teacher_id, weekday_id, lesson_slot_id) VALUES (?, ?, ?)",
            [(teacher_id, day, slot) for day, slot in off],
        )
        return teacher_id

    def delete_teacher(self, teacher_id) -> None:
        self.conn.execute("DELETE FROM teachers WHERE id = ?", (teacher_id,))

    def teacher_in_use(self, teacher_id) -> bool:
        return bool(self._one("SELECT 1 FROM workload WHERE teacher_id = ?", teacher_id))

    def classes(self, shift_id=None):
        sql = f"""SELECT c.*, c.grade || c.letter AS name, {TEACHER_SHORT} AS teacher_short, r.number AS room_number
            FROM classes c
            LEFT JOIN teachers t ON t.id = c.class_teacher_id
            LEFT JOIN classrooms r ON r.id = c.home_classroom_id"""
        if shift_id:
            return self._all(sql + " WHERE c.shift_id = ? ORDER BY c.grade, c.letter", shift_id)
        return self._all(sql + " ORDER BY c.grade, c.letter")

    def save_class(self, class_id, grade, letter, shift_id, study_days, students, teacher_id, room_id) -> None:
        values = (grade, letter, shift_id, study_days, students, teacher_id, room_id)
        if class_id:
            self.conn.execute(
                """UPDATE classes SET grade = ?, letter = ?, shift_id = ?, study_days = ?, students_count = ?,
                class_teacher_id = ?, home_classroom_id = ? WHERE id = ?""",
                (*values, class_id),
            )
        else:
            self.conn.execute(
                """INSERT INTO classes (grade, letter, shift_id, study_days, students_count,
                class_teacher_id, home_classroom_id) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                values,
            )

    def delete_class(self, class_id) -> None:
        self.conn.execute("DELETE FROM classes WHERE id = ?", (class_id,))

    def class_in_use(self, class_id) -> bool:
        return bool(self._one("SELECT 1 FROM workload WHERE class_id = ?", class_id))

    def subjects(self):
        return self._all(
            """SELECT s.*, rt.name AS room_type_name FROM subjects s
            LEFT JOIN room_types rt ON rt.id = s.required_room_type_id
            ORDER BY s.name"""
        )

    def subject_scores(self, subject_id) -> dict[int, int]:
        rows = self._all("SELECT grade, score FROM subject_difficulty WHERE subject_id = ?", subject_id)
        return {r["grade"]: r["score"] for r in rows}

    def save_subject(self, subject_id, name, short_name, room_type_id, scores: dict[int, int | None]) -> int:
        short_name = _blank_to_none(short_name)
        if subject_id:
            self.conn.execute(
                "UPDATE subjects SET name = ?, short_name = ?, required_room_type_id = ? WHERE id = ?",
                (name, short_name, room_type_id, subject_id),
            )
        else:
            subject_id = self.conn.execute(
                "INSERT INTO subjects (name, short_name, required_room_type_id) VALUES (?, ?, ?)",
                (name, short_name, room_type_id),
            ).lastrowid
        self.conn.execute("DELETE FROM subject_difficulty WHERE subject_id = ?", (subject_id,))
        self.conn.executemany(
            "INSERT INTO subject_difficulty (subject_id, grade, score) VALUES (?, ?, ?)",
            [(subject_id, grade, score) for grade, score in scores.items() if score],
        )
        return subject_id

    def delete_subject(self, subject_id) -> None:
        self.conn.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))

    def subject_in_use(self, subject_id) -> bool:
        return bool(self._one("SELECT 1 FROM workload WHERE subject_id = ?", subject_id))

    def workload(self, version_id, class_id=None, workload_id=None):
        sql = f"""SELECT w.*, c.grade || c.letter AS class_name, c.grade, c.study_days, c.shift_id,
                c.home_classroom_id, c.students_count,
                s.name AS subject_name, COALESCE(s.short_name, s.name) AS subject_short,
                s.required_room_type_id, {TEACHER_SHORT} AS teacher_short,
                (SELECT COUNT(*) FROM schedule x WHERE x.workload_id = w.id AND x.version_id = ?) AS placed
            FROM workload w
            JOIN classes c ON c.id = w.class_id
            JOIN subjects s ON s.id = w.subject_id
            JOIN teachers t ON t.id = w.teacher_id"""
        order = " ORDER BY c.grade, c.letter, s.name, w.subgroup"
        if workload_id:
            return self._all(sql + " WHERE w.id = ?", version_id, workload_id)
        if class_id:
            return self._all(sql + " WHERE w.class_id = ?" + order, version_id, class_id)
        return self._all(sql + order, version_id)

    def workload_item(self, version_id, workload_id):
        return self.workload(version_id, workload_id=workload_id)[0]

    def save_workload(self, workload_id, class_id, subject_id, subgroup, teacher_id, lessons) -> None:
        if workload_id:
            self.conn.execute(
                """UPDATE workload SET class_id = ?, subject_id = ?, subgroup = ?, teacher_id = ?,
                lessons_per_fortnight = ? WHERE id = ?""",
                (class_id, subject_id, subgroup, teacher_id, lessons, workload_id),
            )
        else:
            self.conn.execute(
                """INSERT INTO workload (class_id, subject_id, subgroup, teacher_id, lessons_per_fortnight)
                VALUES (?, ?, ?, ?, ?)""",
                (class_id, subject_id, subgroup, teacher_id, lessons),
            )

    def delete_workload(self, workload_id) -> None:
        self.conn.execute("DELETE FROM schedule WHERE workload_id = ?", (workload_id,))
        self.conn.execute("DELETE FROM workload WHERE id = ?", (workload_id,))

    def workload_lessons_count(self, workload_id) -> int:
        return self._one("SELECT COUNT(*) AS n FROM schedule WHERE workload_id = ?", workload_id)["n"]

    def versions(self):
        return self._all("SELECT * FROM schedule_versions ORDER BY id")

    def copy_version(self, source_id, name) -> int:
        new_id = self.conn.execute("INSERT INTO schedule_versions (name) VALUES (?)", (name,)).lastrowid
        self.conn.execute(
            """INSERT INTO schedule (version_id, workload_id, week_type_id, weekday_id, lesson_slot_id, classroom_id)
            SELECT ?, workload_id, week_type_id, weekday_id, lesson_slot_id, classroom_id
            FROM schedule WHERE version_id = ?""",
            (new_id, source_id),
        )
        return new_id

    def set_active_version(self, version_id) -> None:
        # сначала снимаем: уникальный индекс не допускает двух действующих
        self.conn.execute("UPDATE schedule_versions SET is_active = 0")
        self.conn.execute("UPDATE schedule_versions SET is_active = 1 WHERE id = ?", (version_id,))

    def lessons(self, version_id, week_id=None):
        sql = f"""SELECT sc.*, w.class_id, w.subject_id, w.subgroup, w.teacher_id,
                c.grade, c.grade || c.letter AS class_name, c.students_count,
                s.name AS subject_name, COALESCE(s.short_name, s.name) AS subject_short,
                s.required_room_type_id, {TEACHER_SHORT} AS teacher_short,
                r.number AS room_number, r.capacity AS room_capacity, r.room_type_id,
                ls.number AS lesson_number, COALESCE(sd.score, 0) AS score
            FROM schedule sc
            JOIN workload w ON w.id = sc.workload_id
            JOIN classes c ON c.id = w.class_id
            JOIN subjects s ON s.id = w.subject_id
            JOIN teachers t ON t.id = w.teacher_id
            JOIN lesson_slots ls ON ls.id = sc.lesson_slot_id
            LEFT JOIN classrooms r ON r.id = sc.classroom_id
            LEFT JOIN subject_difficulty sd ON sd.subject_id = w.subject_id AND sd.grade = c.grade
            WHERE sc.version_id = ?"""
        if week_id:
            return self._all(sql + " AND sc.week_type_id = ?", version_id, week_id)
        return self._all(sql, version_id)

    def lesson(self, lesson_id):
        return self._one("SELECT * FROM schedule WHERE id = ?", lesson_id)

    def lesson_twin(self, lesson):
        """Тот же урок на другой неделе: урок "каждую неделю" хранится двумя строками."""
        return self._one(
            """SELECT * FROM schedule WHERE version_id = ? AND workload_id = ? AND weekday_id = ?
            AND lesson_slot_id = ? AND week_type_id <> ?""",
            lesson["version_id"], lesson["workload_id"], lesson["weekday_id"],
            lesson["lesson_slot_id"], lesson["week_type_id"],
        )

    def add_lesson(self, version_id, workload_id, week_id, day_id, slot_id, room_id) -> None:
        self.conn.execute(
            """INSERT INTO schedule (version_id, workload_id, week_type_id, weekday_id, lesson_slot_id, classroom_id)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (version_id, workload_id, week_id, day_id, slot_id, room_id),
        )

    def move_lesson(self, lesson_id, day_id, slot_id, room_id) -> None:
        self.conn.execute(
            "UPDATE schedule SET weekday_id = ?, lesson_slot_id = ?, classroom_id = ? WHERE id = ?",
            (day_id, slot_id, room_id, lesson_id),
        )

    def delete_lessons(self, lesson_ids: Iterable[int]) -> None:
        self.conn.executemany("DELETE FROM schedule WHERE id = ?", [(i,) for i in lesson_ids])

    def grades_in_use(self) -> list[int]:
        return [r["grade"] for r in self._all("SELECT DISTINCT grade FROM classes ORDER BY grade")]

    def grade_limit(self, grade) -> int | None:
        return self._one("SELECT max_daily_lessons AS n FROM grades WHERE number = ?", grade)["n"]

    def set_grade_limit(self, grade, limit) -> None:
        self.conn.execute("UPDATE grades SET max_daily_lessons = ? WHERE number = ?", (limit, grade))
