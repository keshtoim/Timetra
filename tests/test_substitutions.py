import datetime
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests.test_repo import RepoCase
from timetra.db.connection import SCHEMA_PATH, connect
from timetra.services.substitutions import (
    check_substitution,
    day_lessons,
    describe_change,
    export_rows,
    free_teacher_ids,
    parse_date,
    week_for_date,
)

MONDAY, NEXT_MONDAY, TUESDAY = "2026-11-02", "2026-11-09", "2026-11-03"


class SubstitutionCase(RepoCase):
    def setUp(self):
        super().setUp()
        with self.conn:
            self.repo.save_room(None, "101", 30, 1)
            self.repo.save_room(None, "102", 30, 1)
            self.r1, self.r2 = [r["id"] for r in self.repo.rooms()]
            music = self.repo.save_subject(None, "Музыка", "Муз.", None, {})
            self.t2 = self.repo.save_teacher(None, "Петрова", "Анна", "", [self.subject])
            self.repo.save_class(None, 5, "Б", 1, 5, 24, None, None)
            self.cls2 = next(x["id"] for x in self.repo.classes() if x["letter"] == "Б")
            self.repo.save_workload(None, self.cls2, music, 0, self.t2, 2)
            self.music = music
            self.wl2 = next(w["id"] for w in self.repo.workload(self.ver) if w["class_id"] == self.cls2)
            self.repo.add_lesson(self.ver, self.wl, 1, 1, self.slot, self.r1)
            self.repo.add_lesson(self.ver, self.wl2, 1, 1, self.slot, self.r2)
        rows = {x["workload_id"]: x["id"] for x in self.repo.lessons(self.ver)}
        self.lesson, self.lesson2 = rows[self.wl], rows[self.wl2]

    def insert(self, lesson, date=MONDAY, room=None, cancelled=0):
        self.conn.execute(
            "INSERT INTO substitutions (schedule_id, lesson_date, classroom_id, is_cancelled) VALUES (?, ?, ?, ?)",
            (lesson, date, room, cancelled),
        )


class TableTest(SubstitutionCase):
    def test_busy_room_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert(self.lesson, room=self.r2)

    def test_room_freed_by_other_substitution_or_cancellation(self):
        self.insert(self.lesson2, cancelled=1)
        self.insert(self.lesson, room=self.r2)

    def test_room_taken_by_other_substitution_rejected(self):
        with self.conn:
            self.repo.save_room(None, "103", 30, 1)
        r3 = next(r["id"] for r in self.repo.rooms() if r["number"] == "103")
        self.insert(self.lesson, room=r3)
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert(self.lesson2, room=r3)

    def test_same_room_free_on_other_date(self):
        with self.conn:
            self.repo.save_room(None, "103", 30, 1)
        r3 = next(r["id"] for r in self.repo.rooms() if r["number"] == "103")
        self.insert(self.lesson, room=r3)
        self.insert(self.lesson2, date=NEXT_MONDAY, room=r3)

    def test_update_into_busy_room_rejected(self):
        self.insert(self.lesson)
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE substitutions SET classroom_id = ?", (self.r2,))

    def test_date_must_match_lesson_weekday(self):
        with self.assertRaisesRegex(sqlite3.IntegrityError, "днём"):
            self.insert(self.lesson, date=TUESDAY)

    def test_one_substitution_per_lesson_and_date(self):
        self.insert(self.lesson)
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert(self.lesson)

    def test_deleted_with_lesson(self):
        self.insert(self.lesson)
        self.conn.commit()
        with self.conn:
            self.repo.delete_lessons([self.lesson])
        self.assertIsNone(self.conn.execute("SELECT 1 FROM substitutions").fetchone())

    def test_move_to_other_day_drops_substitution_but_same_day_keeps(self):
        self.insert(self.lesson)
        with self.conn:
            self.repo.move_lesson(self.lesson, 1, self.repo.slots(1)[1]["id"], self.r1)
        self.assertIsNotNone(self.conn.execute("SELECT 1 FROM substitutions").fetchone())
        with self.conn:
            self.repo.move_lesson(self.lesson, 2, self.slot, self.r1)
        self.assertIsNone(self.conn.execute("SELECT 1 FROM substitutions").fetchone())


class WeekTest(unittest.TestCase):
    def test_parity_alternates_and_ignores_year_boundary(self):
        self.assertEqual(week_for_date(datetime.date(2024, 1, 1), 0), 1)
        self.assertEqual(week_for_date(datetime.date(2024, 1, 7), 0), 1)
        self.assertEqual(week_for_date(datetime.date(2024, 1, 8), 0), 2)
        monday = datetime.date(2026, 12, 28)
        self.assertNotEqual(week_for_date(monday, 0), week_for_date(monday + datetime.timedelta(days=7), 0))

    def test_offset_swaps(self):
        date = datetime.date(2026, 11, 2)
        self.assertNotEqual(week_for_date(date, 0), week_for_date(date, 1))

    def test_parse_date(self):
        self.assertEqual(parse_date(" 02.11.2026 "), datetime.date(2026, 11, 2))
        self.assertIsNone(parse_date("31.02.2026"))
        self.assertIsNone(parse_date("завтра"))


class LogicTest(SubstitutionCase):
    def setUp(self):
        super().setUp()
        self.date = datetime.date.fromisoformat(MONDAY)
        self.offset = 0 if week_for_date(self.date, 0) == 1 else 1

    def rows(self, date=None):
        return day_lessons(self.repo, self.ver, date or self.date, self.offset)

    def row(self, lesson):
        return next(r for r in self.rows() if r["lesson_id"] == lesson)

    def check(self, lesson, teacher, subject, room):
        return check_substitution(self.repo, self.ver, self.date, self.offset, self.row(lesson), teacher, subject, room)

    def save(self, lesson, teacher=None, subject=None, room=None, cancelled=False, note="", date=MONDAY):
        with self.conn:
            self.repo.save_substitution(lesson, date, teacher, subject, room, cancelled, note)

    def test_effective_values(self):
        self.save(self.lesson, teacher=self.t2, subject=self.music, note="болеет")
        row = self.row(self.lesson)
        self.assertEqual((row["eff_teacher_id"], row["base_teacher_id"]), (self.t2, self.teacher))
        self.assertEqual(row["new_subject"], "Музыка")
        self.assertEqual(row["eff_room_id"], self.r1)
        self.assertEqual(describe_change(row), "Учитель: Петрова А., Предмет: Музыка")

    def test_substitution_only_on_its_date(self):
        self.save(self.lesson, teacher=self.t2)
        other = datetime.date.fromisoformat("2026-11-16")
        self.assertIsNone(next(r for r in self.rows(other) if r["lesson_id"] == self.lesson)["substitution_id"])

    def test_resave_replaces(self):
        self.save(self.lesson, teacher=self.t2)
        self.save(self.lesson, cancelled=True)
        row = self.row(self.lesson)
        self.assertEqual(row["eff_teacher_id"], self.teacher)
        self.assertEqual(describe_change(row), "Урока не будет")

    def test_lessons_of_other_week_not_shown(self):
        self.assertEqual(self.rows(datetime.date.fromisoformat(NEXT_MONDAY)), [])

    def test_sunday_empty(self):
        self.assertEqual(self.rows(datetime.date(2026, 11, 8)), [])

    def test_busy_teacher_warns_room_blocks(self):
        result = self.check(self.lesson, self.t2, self.subject, None)
        self.assertIsNone(result.room_busy)
        self.assertIn("5Б", result.warnings[0])
        self.assertIn("занят", self.check(self.lesson, self.teacher, self.subject, self.r2).room_busy)

    def test_check_counts_other_substitutions(self):
        self.save(self.lesson2, cancelled=True)
        result = self.check(self.lesson, self.t2, self.subject, self.r2)
        self.assertIsNone(result.room_busy)
        self.assertEqual(result.warnings, [])

    def test_free_teachers(self):
        with self.conn:
            t3 = self.repo.save_teacher(None, "Сидоров", "Иван", "")
            t4 = self.repo.save_teacher(None, "Орлов", "Пётр", "", [], [(1, self.slot)])
        free = free_teacher_ids(self.repo, self.ver, self.date, self.offset, self.row(self.lesson))
        self.assertIn(t3, free)
        self.assertIn(self.teacher, free)
        self.assertNotIn(self.t2, free)
        self.assertNotIn(t4, free)

    def test_unqualified_warns(self):
        with self.conn:
            t3 = self.repo.save_teacher(None, "Сидоров", "Иван", "", [self.music])
        self.assertIn("не отмечен", self.check(self.lesson, t3, self.subject, None).warnings[0])

    def test_export_only_changes(self):
        self.save(self.lesson, teacher=self.t2, note="болеет")
        rows = export_rows(self.rows())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "5А")
        self.assertEqual(rows[0][-1], "болеет")


class UpgradeTest(unittest.TestCase):
    def test_old_database_gets_table_and_keeps_data(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "old.db"
            old = sqlite3.connect(path)
            old.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            old.execute("INSERT INTO subjects (name) VALUES ('Шахматы')")
            old.execute("PRAGMA user_version = 2")
            old.commit()
            old.close()
            conn = connect(path)
            conn.execute("SELECT * FROM substitutions")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM subjects").fetchone()[0], 1)
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 2)
            conn.close()
            conn = connect(path)
            conn.close()


if __name__ == "__main__":
    unittest.main()
