import datetime
import unittest

from tests.test_schedule_ui import ScheduleCase
from timetra.io.tables import read_table
from timetra.services.substitutions import week_for_date
from timetra.ui.substitutions_screen import SubstitutionDialog

MONDAY = datetime.date(2026, 11, 2)


class SubstitutionsScreenCase(ScheduleCase):
    def setUp(self):
        super().setUp()
        self.app.settings.week_offset = 0 if week_for_date(MONDAY, 0) == 1 else 1
        self.app.substitutions_state.date = MONDAY
        with self.conn:
            self.repo.add_lesson(self.ver, self.w1, 1, 1, self.slot, self.r1)
            self.repo.add_lesson(self.ver, self.w3, 1, 1, self.slot, self.r2)
        self.open()

    def open(self):
        self.app.go("substitutions")
        self.app.update()
        self.sub_screen = self.app.current_screen

    def row(self, workload):
        return next(r for r in self.sub_screen.rows if r["workload_id"] == workload)

    def dialog(self, workload):
        return SubstitutionDialog(self.sub_screen, self.row(workload))

    def saved(self):
        return self.conn.execute("SELECT * FROM substitutions").fetchall()


class ScreenTest(SubstitutionsScreenCase):
    def test_lists_lessons_of_date(self):
        self.assertEqual({r["workload_id"] for r in self.sub_screen.rows}, {self.w1, self.w3})

    def test_change_teacher_then_undo(self):
        dialog = self.dialog(self.w1)
        dialog.teacher.set_value(self.t2)
        dialog.save()
        self.app.update()
        self.assertEqual(self.saved()[0]["teacher_id"], self.t2)
        self.assertIsNone(self.saved()[0]["classroom_id"])
        self.app.undo()
        self.assertEqual(self.saved(), [])

    def test_busy_room_blocks_save(self):
        dialog = self.dialog(self.w1)
        dialog.room.set_value(self.r2)
        dialog.update_notes()
        dialog.save()
        self.app.update()
        self.assertTrue(dialog.winfo_exists())
        self.assertEqual(self.saved(), [])
        dialog.destroy()

    def test_busy_teacher_only_warns_and_saves(self):
        dialog = self.dialog(self.w1)
        dialog.teacher.set_value(self.t2)
        self.assertTrue(dialog._check().warnings)
        dialog.save()
        self.assertEqual(len(self.saved()), 1)

    def test_cancel_lesson_allowed_and_frees_room(self):
        dialog = self.dialog(self.w3)
        dialog.cancelled.set(True)
        dialog.save()
        self.app.update()
        self.assertEqual(self.saved()[0]["is_cancelled"], 1)
        dialog = SubstitutionDialog(self.app.current_screen, next(r for r in self.app.current_screen.rows if r["workload_id"] == self.w1))
        dialog.room.set_value(self.r2)
        dialog.save()
        self.assertEqual(len(self.saved()), 2)

    def test_note_only_kept_and_remove(self):
        dialog = self.dialog(self.w1)
        dialog.note.insert(0, "экскурсия")
        dialog.save()
        self.app.update()
        self.assertEqual(self.saved()[0]["note"], "экскурсия")
        dialog = SubstitutionDialog(self.app.current_screen, next(r for r in self.app.current_screen.rows if r["workload_id"] == self.w1))
        dialog.remove()
        self.assertEqual(self.saved(), [])

    def test_resetting_to_base_removes_substitution(self):
        with self.conn:
            self.repo.save_substitution(self.row(self.w1)["lesson_id"], MONDAY.isoformat(), self.t2, None, None, False, "")
        self.open()
        dialog = self.dialog(self.w1)
        dialog.teacher.set_value(self.t1)
        dialog.save()
        self.assertEqual(self.saved(), [])

    def test_filters(self):
        state = self.app.substitutions_state
        state.teacher_id = self.t2
        self.open()
        self.assertEqual([r["workload_id"] for r in self.sub_screen._visible_rows()], [self.w3])
        state.teacher_id = None
        state.only_changed = True
        self.open()
        self.assertEqual(self.sub_screen._visible_rows(), [])

    def test_week_switch_remembered_for_all_dates(self):
        offset = self.app.settings.week_offset
        self.sub_screen.set_week(2)
        self.app.update()
        self.assertEqual(self.app.settings.week_offset, 1 - offset)
        self.assertEqual(self.app.current_screen.rows, [])

    def test_date_navigation_and_bad_input(self):
        self.sub_screen.set_date(MONDAY + datetime.timedelta(days=6))
        self.app.update()
        self.assertEqual(self.app.current_screen.rows, [])
        screen = self.app.current_screen
        screen.date_entry.delete(0, "end")
        screen.date_entry.insert(0, "вчера")
        screen.apply_entered_date()
        self.assertEqual(self.app.substitutions_state.date, MONDAY + datetime.timedelta(days=6))
        screen.date_entry.delete(0, "end")
        screen.date_entry.insert(0, "02.11.2026")
        screen.apply_entered_date()
        self.app.update()
        self.assertEqual(self.app.substitutions_state.date, MONDAY)

    def test_uses_active_version_not_open_draft(self):
        with self.conn:
            draft = self.repo.copy_version(self.ver, "Черновик")
            self.repo.delete_version_lessons(draft)
        self.app.version_id = draft
        self.open()
        self.assertEqual(len(self.sub_screen.rows), 2)

    def test_file_contains_only_changes(self):
        with self.conn:
            self.repo.save_substitution(self.row(self.w1)["lesson_id"], MONDAY.isoformat(), self.t2, None, None, False, "болеет")
        self.open()
        path = self.tmp / "z.xlsx"
        self.sub_screen.write_file(path)
        table = read_table(path)
        self.assertEqual(len(table), 2)
        self.assertEqual(table[1][0], "5А")
        self.assertIn("Петрова", table[1][5])


if __name__ == "__main__":
    unittest.main()
