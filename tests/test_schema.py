import sqlite3
import unittest
from pathlib import Path

SCHEMA = Path(__file__).parents[1] / "db" / "schema.sql"
ODD, EVEN = 1, 2
MONDAY = 1


class SchemaTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.executescript(SCHEMA.read_text(encoding="utf-8"))
        self.db.executescript("""
            INSERT INTO subjects (id, name) VALUES (1, 'Математика'), (2, 'Английский'), (3, 'Музыка');
            INSERT INTO subject_difficulty VALUES (1, 5, 10), (2, 5, 9), (2, 6, 11);
            INSERT INTO teachers (id, last_name, first_name) VALUES (1, 'Иванов', 'Иван'), (2, 'Петрова', 'Анна');
            INSERT INTO classes (id, grade, letter) VALUES (1, 5, 'А'), (2, 5, 'Б');
            INSERT INTO workload (id, class_id, subject_id, subgroup, teacher_id, lessons_per_fortnight) VALUES
                (1, 1, 1, 0, 1, 10),
                (2, 1, 2, 1, 1, 6),
                (3, 1, 2, 2, 2, 6),
                (4, 2, 1, 0, 1, 10),
                (5, 2, 3, 0, 2, 1);
        """)

    def place(self, workload_id, week=ODD, lesson=1):
        self.db.execute(
            "INSERT INTO schedule (workload_id, week_type_id, weekday_id, lesson_number) VALUES (?, ?, ?, ?)",
            (workload_id, week, MONDAY, lesson),
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

    def test_subgroups_may_run_in_parallel(self):
        self.place(2)
        self.place(3)
        self.assertEqual(self.conflicts(), [])

    def test_whole_class_overlaps_subgroup(self):
        self.place(1)
        self.place(3)
        self.assertEqual(self.conflicts(), ["class"])

    def test_daily_difficulty_counts_parallel_subgroups_once(self):
        self.place(2, lesson=1)
        self.place(3, lesson=1)
        self.place(1, lesson=2)
        total = self.db.execute("SELECT total_score FROM daily_difficulty WHERE class_id = 1").fetchone()[0]
        self.assertEqual(total, 19)

    def test_schedule_view_keeps_lesson_without_score(self):
        self.place(5)
        row = self.db.execute("SELECT class_name, subject, teacher, difficulty FROM schedule_view").fetchone()
        self.assertEqual(row, ("5Б", "Музыка", "Петрова Анна", None))

    def test_foreign_key_blocks_deleting_teacher_with_workload(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("DELETE FROM teachers WHERE id = 1")

    def test_duplicate_class_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO classes (grade, letter) VALUES (5, 'А')")


if __name__ == "__main__":
    unittest.main()
