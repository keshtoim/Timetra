import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests.test_repo import RepoCase
from timetra.db.connection import SCHEMA_PATH, connect

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
