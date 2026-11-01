import unittest

from tests.test_repo import RepoCase
from tests.test_ui import UiCase
from timetra.services.sanpin import SEEDED_VERSION, SUBJECTS, fill_subjects, format_scores, sanpin_scores, seed_once
from timetra.ui.dialogs import FormDialog


class TableTest(unittest.TestCase):
    def test_spot_values_from_tables(self):
        cases = [
            ("Математика", 1, 8), ("Математика", 6, 13), ("Физика", 9, 13), ("Физика", 11, 12),
            ("Химия", 8, 10), ("Геометрия", 7, 12), ("Геометрия", 10, 11), ("Алгебра", 10, 10),
            ("Русский язык", 4, 7), ("Родной язык", 6, 12), ("Иностранный язык", 11, 8), ("Физическая культура", 1, 1),
            ("Физическая культура", 6, 4), ("География", 10, 3), ("Мировая художественная культура", 7, 8),
            ("Литературное чтение", 2, 5), ("Основы безопасности жизнедеятельности", 11, 2),
        ]
        for subject, grade, score in cases:
            self.assertEqual(sanpin_scores(subject)[grade], score, (subject, grade))

    def test_absent_grades_stay_empty(self):
        self.assertNotIn(7, sanpin_scores("Математика"))
        self.assertNotIn(5, sanpin_scores("Физика"))
        self.assertNotIn(4, sanpin_scores("Литература"))
        self.assertNotIn(9, sanpin_scores("Музыка"))
        self.assertNotIn(10, sanpin_scores("Технология"))

    def test_format_scores(self):
        self.assertEqual(format_scores({1: 8, 2: 8, 3: 8, 5: 10, 6: 13}), "1–3: 8; 5: 10; 6: 13")
        self.assertEqual(format_scores({5: 3, 7: 3}), "5: 3; 7: 3")
        self.assertEqual(format_scores({}), "")


class FillTest(RepoCase):
    def names(self):
        return {s["name"] for s in self.repo.subjects()}

    def test_fill_adds_all_and_keeps_own_subjects(self):
        with self.conn:
            own = self.repo.save_subject(None, "Шахматы", "", None, {5: 2})
            fill_subjects(self.repo)
        self.assertTrue(set(SUBJECTS) <= self.names())
        self.assertEqual(self.repo.subject_scores(own), {5: 2})

    def test_fill_does_not_overwrite_school_values_but_reset_does(self):
        with self.conn:
            self.repo.save_subject(self.subject, "Математика", "", None, {5: 99})
            fill_subjects(self.repo)
        scores = self.repo.subject_scores(self.subject)
        self.assertEqual((scores[5], scores[1]), (99, 8))
        with self.conn:
            fill_subjects(self.repo, overwrite=True)
        self.assertEqual(self.repo.subject_scores(self.subject)[5], 10)

    def test_special_rooms_set(self):
        with self.conn:
            fill_subjects(self.repo)
        rows = {s["name"]: s["room_type_name"] for s in self.repo.subjects()}
        self.assertEqual(rows["Физическая культура"], "Спортзал")
        self.assertIsNone(rows["Химия"])

    def test_seed_runs_once_so_deleted_subject_stays_deleted(self):
        seed_once(self.repo)
        self.assertEqual(self.conn.execute("PRAGMA user_version").fetchone()[0], SEEDED_VERSION)
        music = next(s["id"] for s in self.repo.subjects() if s["name"] == "Музыка")
        with self.conn:
            self.repo.delete_subject(music)
        seed_once(self.repo)
        self.assertNotIn("Музыка", self.names())


class SubjectFormTest(UiCase):
    def open_form(self, key):
        from timetra.ui.refs_screen import RefsScreen

        RefsScreen.tab = "subjects"
        self.app.go("refs")
        self.app.update()
        self.app.current_screen.edit(key)
        self.app.update()
        return next(w for w in self.app.winfo_children() if isinstance(w, FormDialog))

    def setUp(self):
        super().setUp()
        with self.conn:
            fill_subjects(self.app.repo)
        self.math = next(s["id"] for s in self.app.repo.subjects() if s["name"] == "Математика")

    def set_score(self, form, grade, text):
        entry = form.inputs["scores"][grade]
        entry.delete(0, "end")
        entry.insert(0, text)

    def test_form_has_all_grades_without_any_classes(self):
        form = self.open_form(self.math)
        self.assertEqual(sorted(form.inputs["scores"]), list(range(1, 12)))
        self.assertEqual(form.inputs["scores"][6].get(), "13")
        form.destroy()

    def test_edit_clear_and_undo(self):
        form = self.open_form(self.math)
        self.set_score(form, 6, "7")
        self.set_score(form, 1, "")
        form.submit()
        self.app.update()
        scores = self.app.repo.subject_scores(self.math)
        self.assertEqual(scores[6], 7)
        self.assertNotIn(1, scores)
        self.app.undo()
        self.assertEqual(self.app.repo.subject_scores(self.math)[6], 13)

    def test_bad_score_rejected(self):
        form = self.open_form(self.math)
        self.set_score(form, 6, "abc")
        form.submit()
        self.assertIn("6 кл.", form.error.cget("text"))
        self.assertEqual(self.app.repo.subject_scores(self.math)[6], 13)
        form.destroy()

    def test_reset_button_restores_and_undoes(self):
        with self.conn:
            self.app.repo.save_subject(self.math, "Математика", "", None, {6: 1})
        self.app.go("refs")
        self.app.current_screen.reset_sanpin()
        self.app.update()
        dialog = [w for w in self.app.winfo_children() if w.winfo_class() == "Toplevel"][0]
        dialog.destroy()
        self.app.mutate("x", lambda: fill_subjects(self.app.repo, overwrite=True))
        self.assertEqual(self.app.repo.subject_scores(self.math)[6], 13)
        self.app.undo()
        self.assertEqual(self.app.repo.subject_scores(self.math)[6], 1)


if __name__ == "__main__":
    unittest.main()
