import sqlite3
import unittest
from pathlib import Path

SCHEMA = Path(__file__).parents[1] / "timetra" / "db" / "schema.sql"
ODD, EVEN = 1, 2
MONDAY = 1
FIRST_SHIFT_LESSON_1, FIRST_SHIFT_LESSON_2, FIRST_SHIFT_LESSON_6, SECOND_SHIFT_LESSON_1, SECOND_SHIFT_LESSON_2 = 1, 2, 3, 4, 5
ROOM_1, ROOM_2 = 1, 2


class SchemaTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA.read_text(encoding="utf-8"))
        self.db.executescript("""
            INSERT INTO lesson_slots (id, shift_id, number, starts_at, ends_at) VALUES
                (1, 1, 1, '08:00', '08:45'),
                (2, 1, 2, '08:55', '09:40'),
                (3, 1, 6, '13:00', '13:45'),
                (4, 2, 1, '13:30', '14:15'),
                (5, 2, 2, '14:25', '15:10');
            INSERT INTO classrooms (id, number, room_type_id) VALUES (1, '101', 1), (2, '102', 1);
            INSERT INTO subjects (id, name) VALUES (1, 'Математика'), (2, 'Английский'), (3, 'Музыка');
            INSERT INTO subject_difficulty VALUES (1, 5, 10), (2, 5, 9), (2, 6, 11);
            INSERT INTO teachers (id, last_name, first_name) VALUES (1, 'Иванов', 'Иван'), (2, 'Петрова', 'Анна');
            INSERT INTO classes (id, grade, letter, shift_id) VALUES (1, 5, 'А', 1), (2, 5, 'Б', 1), (3, 6, 'А', 2);
            INSERT INTO workload (id, class_id, subject_id, subgroup, teacher_id, lessons_per_fortnight) VALUES
                (1, 1, 1, 0, 1, 10),
                (2, 1, 2, 1, 1, 6),
                (3, 1, 2, 2, 2, 6),
                (4, 2, 1, 0, 1, 10),
                (5, 2, 3, 0, 2, 1),
                (6, 3, 1, 0, 1, 10);
            INSERT INTO schedule_versions (id, name) VALUES (1, 'Черновик'), (2, 'Запасной');
        """)

    def place(self, workload_id, week=ODD, slot=FIRST_SHIFT_LESSON_1, room=None, version=1):
        self.db.execute(
            "INSERT INTO schedule (version_id, workload_id, week_type_id, weekday_id, lesson_slot_id, classroom_id)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (version, workload_id, week, MONDAY, slot, room),
        )

    def conflicts(self):
        return [row[0] for row in self.db.execute("SELECT conflict_type FROM schedule_conflicts")]

    def test_teacher_conflict(self):
        self.place(1)
        self.place(4)
        self.assertEqual(self.conflicts(), ["teacher"])

    def test_no_conflict_between_week_types(self):
        self.place(1, ODD)
        self.place(4, EVEN)
        self.assertEqual(self.conflicts(), [])

    def test_no_conflict_between_versions(self):
        self.place(1, version=1)
        self.place(4, version=2)
        self.assertEqual(self.conflicts(), [])

    def test_subgroups_may_run_in_parallel(self):
        self.place(2)
        self.place(3)
        self.assertEqual(self.conflicts(), [])

    def test_whole_class_overlaps_subgroup(self):
        self.place(1)
        self.place(3)
        self.assertEqual(self.conflicts(), ["class"])

    def test_busy_classroom_rejected(self):
        self.place(1, room=ROOM_1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.place(5, room=ROOM_1)

    def test_busy_classroom_rejected_across_shifts_by_time(self):
        self.place(1, slot=FIRST_SHIFT_LESSON_6, room=ROOM_1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.place(6, slot=SECOND_SHIFT_LESSON_1, room=ROOM_1)

    def test_classroom_free_in_other_week_or_version(self):
        self.place(1, room=ROOM_1)
        self.place(5, week=EVEN, room=ROOM_1)
        self.place(5, version=2, room=ROOM_1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM schedule").fetchone()[0], 3)

    def test_moving_lesson_into_busy_classroom_rejected(self):
        self.place(1, room=ROOM_1)
        self.place(5, slot=FIRST_SHIFT_LESSON_2, room=ROOM_1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE schedule SET lesson_slot_id = ? WHERE workload_id = 5", (FIRST_SHIFT_LESSON_1,))

    def test_updating_lesson_does_not_clash_with_itself(self):
        self.place(1, room=ROOM_1)
        self.db.execute("UPDATE schedule SET classroom_id = ? WHERE workload_id = 1", (ROOM_1,))

    def test_unassigned_classrooms_do_not_conflict(self):
        self.place(4)
        self.place(3)
        self.assertEqual(self.conflicts(), [])

    def test_teacher_conflict_across_shifts_by_time(self):
        self.place(1, slot=FIRST_SHIFT_LESSON_6)
        self.place(6, slot=SECOND_SHIFT_LESSON_1)
        self.assertEqual(self.conflicts(), ["teacher"])

    def test_no_conflict_across_shifts_when_time_differs(self):
        self.place(1, slot=FIRST_SHIFT_LESSON_6)
        self.place(6, slot=SECOND_SHIFT_LESSON_2)
        self.assertEqual(self.conflicts(), [])

    def test_daily_difficulty_counts_parallel_subgroups_once(self):
        self.place(2, slot=FIRST_SHIFT_LESSON_1)
        self.place(3, slot=FIRST_SHIFT_LESSON_1)
        self.place(1, slot=FIRST_SHIFT_LESSON_2)
        total = self.db.execute("SELECT total_score FROM daily_difficulty WHERE class_id = 1").fetchone()[0]
        self.assertEqual(total, 19)

    def test_schedule_view_keeps_lesson_without_score_and_room(self):
        self.place(5)
        row = self.db.execute("SELECT class_name, subject, teacher, classroom, difficulty FROM schedule_view").fetchone()
        self.assertEqual(row, ("5Б", "Музыка", "Петрова Анна", None, None))

    def test_only_one_active_version(self):
        self.db.execute("UPDATE schedule_versions SET is_active = 1 WHERE id = 1")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE schedule_versions SET is_active = 1 WHERE id = 2")

    def test_deleting_version_removes_its_lessons(self):
        self.place(1)
        self.db.execute("DELETE FROM schedule_versions WHERE id = 1")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM schedule").fetchone()[0], 0)

    def test_deleting_classroom_keeps_lesson_without_room(self):
        self.place(1, room=ROOM_2)
        self.db.execute("DELETE FROM classrooms WHERE id = ?", (ROOM_2,))
        self.assertIsNone(self.db.execute("SELECT classroom_id FROM schedule").fetchone()[0])

    def test_foreign_key_blocks_deleting_teacher_with_workload(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("DELETE FROM teachers WHERE id = 1")

    def test_duplicate_class_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO classes (grade, letter, shift_id) VALUES (5, 'А', 1)")

    def test_lesson_must_end_after_start(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO lesson_slots (shift_id, number, starts_at, ends_at) VALUES (1, 9, '10:00', '09:00')")


if __name__ == "__main__":
    unittest.main()
