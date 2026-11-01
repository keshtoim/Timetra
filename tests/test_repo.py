import sqlite3
import tempfile
import unittest
from pathlib import Path

from timetra.db.connection import connect
from timetra.db.repo import DEFAULT_LESSONS_COUNT, Repo


class RepoCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.conn = connect(Path(tmp.name) / "t.db")
        self.addCleanup(self.conn.close)
        self.repo = Repo(self.conn)
        self.repo.ensure_defaults()
        self.ver = self.repo.versions()[0]["id"]
        with self.conn:
            self.teacher = self.repo.save_teacher(None, "Иванова", "Мария", "Сергеевна")
            self.subject = self.repo.save_subject(None, "Математика", "Матем.", None, {5: 10})
            self.repo.save_class(None, 5, "А", 1, 5, 26, None, None)
            self.cls = self.repo.classes()[0]["id"]
            self.repo.save_workload(None, self.cls, self.subject, 0, self.teacher, 10)
            self.wl = self.repo.workload(self.ver)[0]["id"]
        self.slot = self.repo.slots(1)[0]["id"]


class RepoTest(RepoCase):
    def test_defaults_created_once(self):
        self.repo.ensure_defaults()
        self.assertEqual(len(self.repo.versions()), 1)
        self.assertEqual(self.repo.versions()[0]["is_active"], 1)
        self.assertEqual(len(self.repo.slots(1)), DEFAULT_LESSONS_COUNT)

    def test_teacher_short_name(self):
        self.assertEqual(self.repo.teachers()[0]["short"], "Иванова М. С.")

    def test_teacher_without_patronymic(self):
        with self.conn:
            self.repo.save_teacher(self.teacher, "Морозов", "Дмитрий", "")
        row = self.repo.teachers()[0]
        self.assertEqual((row["short"], row["full_name"]), ("Морозов Д.", "Морозов Дмитрий"))

    def test_teacher_subjects_and_off_replaced_on_save(self):
        with self.conn:
            self.repo.save_teacher(self.teacher, "И", "М", "", [self.subject], [(1, self.slot)])
            self.repo.save_teacher(self.teacher, "И", "М", "", [], [(2, self.slot)])
        self.assertEqual(self.repo.teacher_subject_ids(self.teacher), set())
        self.assertEqual(self.repo.teacher_off(self.teacher), {(2, self.slot)})

    def test_empty_score_not_stored(self):
        with self.conn:
            self.repo.save_subject(self.subject, "Математика", "", None, {5: None, 6: 13})
        self.assertEqual(self.repo.subject_scores(self.subject), {6: 13})

    def test_undo_restores_data_and_foreign_keys(self):
        before = self.repo.snapshot()
        with self.conn:
            self.repo.save_teacher(None, "Новый", "Учитель", "")
        self.repo.restore(before)
        self.assertEqual(len(self.repo.teachers()), 1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.delete_teacher(self.teacher)
        self.conn.rollback()

    def test_copy_version_copies_lessons(self):
        with self.conn:
            self.repo.add_lesson(self.ver, self.wl, 1, 1, self.slot, None)
            copy = self.repo.copy_version(self.ver, "Копия")
        self.assertEqual(len(self.repo.lessons(copy)), 1)

    def test_set_active_version_switches(self):
        with self.conn:
            copy = self.repo.copy_version(self.ver, "Копия")
            self.repo.set_active_version(copy)
        self.assertEqual([v["id"] for v in self.repo.versions() if v["is_active"]], [copy])

    def test_lesson_twin(self):
        with self.conn:
            self.repo.add_lesson(self.ver, self.wl, 1, 1, self.slot, None)
            self.repo.add_lesson(self.ver, self.wl, 2, 1, self.slot, None)
        odd, even = self.repo.lessons(self.ver)
        self.assertEqual(self.repo.lesson_twin(odd)["id"], even["id"])

    def test_workload_counts_placed_per_version(self):
        with self.conn:
            self.repo.add_lesson(self.ver, self.wl, 1, 1, self.slot, None)
            copy = self.repo.copy_version(self.ver, "Копия")
            self.repo.add_lesson(copy, self.wl, 2, 1, self.slot, None)
        self.assertEqual(self.repo.workload_item(self.ver, self.wl)["placed"], 1)
        self.assertEqual(self.repo.workload_item(copy, self.wl)["placed"], 2)

    def test_deleting_workload_removes_its_lessons(self):
        with self.conn:
            self.repo.add_lesson(self.ver, self.wl, 1, 1, self.slot, None)
            self.repo.delete_workload(self.wl)
        self.assertEqual(self.repo.lessons(self.ver), [])


if __name__ == "__main__":
    unittest.main()
