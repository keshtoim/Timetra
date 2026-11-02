import datetime
import unittest

from tests.test_schedule_ui import ScheduleCase
from timetra.io.tables import read_table
from timetra.services.substitutions import week_for_date
from timetra.ui.substitutions_screen import ExtraLessonDialog, SubstitutionDialog

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
        return SubstitutionDialog(self.app, self.row(workload))

    def saved(self):
        return self.conn.execute("SELECT * FROM substitutions").fetchall()


class MoveAndExtraTest(SubstitutionsScreenCase):
    def setUp(self):
        super().setUp()
        self.slot3 = self.slots[2]["id"]

    def extras(self):
        return self.conn.execute("SELECT * FROM extra_lessons").fetchall()

    def test_move_lesson_for_one_day(self):
        dialog = self.dialog(self.w1)
        dialog.slot.set_value(self.slot3)
        dialog.save()
        self.app.update()
        self.assertEqual(self.saved()[0]["lesson_slot_id"], self.slot3)
        self.assertEqual(self.repo.lessons(self.ver)[0]["lesson_slot_id"], self.slot)
        row = next(r for r in self.app.current_screen.rows if r["workload_id"] == self.w1)
        self.assertEqual(row["eff_number"], 3)

    def test_move_back_clears_substitution(self):
        with self.conn:
            self.repo.save_substitution(self.row(self.w1)["lesson_id"], MONDAY.isoformat(), None, None, None, False, "", self.slot3)
        self.open()
        dialog = self.dialog(self.w1)
        dialog.slot.set_value(self.slot)
        dialog.save()
        self.assertEqual(self.saved(), [])

    def test_move_into_busy_room_blocked(self):
        with self.conn:
            self.repo.add_lesson(self.ver, self.w2, 1, 1, self.slot3, self.r1)
        self.open()
        dialog = self.dialog(self.w1)
        dialog.slot.set_value(self.slot3)
        dialog.save()
        self.app.update()
        self.assertTrue(dialog.winfo_exists())
        self.assertEqual(self.saved(), [])
        dialog.destroy()

    def test_add_extra_then_edit_and_delete(self):
        dialog = ExtraLessonDialog(self.app, class_id=self.c1, slot_id=self.slot3)
        dialog.subject.set_value(self.s2)
        dialog.teacher.set_value(self.t2)
        dialog.room.set_value(self.r2)
        dialog.note.insert(0, "кружок")
        dialog.save()
        self.app.update()
        row = self.extras()[0]
        self.assertEqual((row["class_id"], row["lesson_slot_id"], row["note"]), (self.c1, self.slot3, "кружок"))
        extra = next(r for r in self.app.current_screen.rows if r["extra_id"])
        dialog = ExtraLessonDialog(self.app, extra)
        dialog.slot.set_value(self.slots[3]["id"])
        dialog.save()
        self.app.update()
        self.assertEqual(len(self.extras()), 1)
        self.assertEqual(self.extras()[0]["lesson_slot_id"], self.slots[3]["id"])
        extra = next(r for r in self.app.current_screen.rows if r["extra_id"])
        ExtraLessonDialog(self.app, extra).remove()
        self.assertEqual(self.extras(), [])

    def test_extra_in_busy_room_blocked(self):
        dialog = ExtraLessonDialog(self.app, class_id=self.c2, slot_id=self.slot)
        dialog.room.set_value(self.r1)
        dialog.save()
        self.app.update()
        self.assertTrue(dialog.winfo_exists())
        self.assertEqual(self.extras(), [])
        dialog.destroy()

    def test_extra_shows_in_table_and_file(self):
        with self.conn:
            self.repo.save_extra(None, self.ver, MONDAY.isoformat(), 1, self.slot3, self.c2, 0, self.s2, self.t2, None, "")
        self.open()
        index = next(i for i, r in enumerate(self.sub_screen.visible) if r["extra_id"])
        self.sub_screen.edit(index)
        self.app.update()
        dialogs = [w for w in self.app.winfo_children() if isinstance(w, ExtraLessonDialog)]
        self.assertEqual(len(dialogs), 1)
        dialogs[0].destroy()
        path = self.tmp / "e.xlsx"
        self.sub_screen.write_file(path)
        self.assertIn("Дополнительный урок", read_table(path)[1][5])

    def test_class_change_updates_lessons_list(self):
        dialog = ExtraLessonDialog(self.app, class_id=self.c1)
        self.assertEqual(dialog.slot.value(), self.slots[0]["id"])
        dialog._class_changed(self.c2)
        self.assertEqual(dialog.slot.value(), self.slots[0]["id"])
        dialog.destroy()


class DateGridTest(SubstitutionsScreenCase):
    def open_grid(self):
        self.app.schedule_state.view = "date"
        self.app.go("schedule")
        self.app.update()
        return self.app.current_screen

    def card(self, screen, workload):
        return next(x[4] for x in screen.grid_view.cards if x[4]["row"]["workload_id"] == workload)

    def lesson_id(self, workload):
        return self.row(workload)["lesson_id"]

    def test_shows_day_without_changes_and_no_panel(self):
        screen = self.open_grid()
        self.assertEqual(len(screen.grid_view.cards), 2)
        self.assertEqual(screen.grid_view.levels, {})

    def test_changes_marked_and_applied(self):
        with self.conn:
            self.repo.save_substitution(self.lesson_id(self.w1), MONDAY.isoformat(), self.t2, None, None, False, "", self.slots[3]["id"])
            self.repo.save_substitution(self.lesson_id(self.w3), MONDAY.isoformat(), None, None, None, True, "")
            self.repo.save_extra(None, self.ver, MONDAY.isoformat(), 1, self.slots[4]["id"], self.c2, 0, self.s2, self.t2, None, "")
        grid = self.open_grid().grid_view
        moved = next(x[4] for x in grid.cards if x[4]["row"]["workload_id"] == self.w1)
        self.assertEqual(moved["lesson_slot_id"], self.slots[3]["id"])
        self.assertEqual(moved["teacher_short"], "Петрова А.")
        flags = sorted(v[2] for v in grid.levels.values())
        self.assertEqual(flags, ["Доп. урок", "Отмена", "Перенос"])
        self.assertIn("Перенос", grid._card_lines(moved))

    def test_drag_moves_only_this_day(self):
        screen = self.open_grid()
        target = screen._columns()[0][0]
        screen.move_lesson(self.card(screen, self.w1), target, self.slots[2]["id"])
        self.app.update()
        self.assertEqual(self.saved()[0]["lesson_slot_id"], self.slots[2]["id"])
        self.assertTrue(all(r["lesson_slot_id"] == self.slot for r in self.repo.lessons(self.ver)))

    def test_drag_back_removes_substitution_and_keeps_other_changes(self):
        with self.conn:
            self.repo.save_substitution(self.lesson_id(self.w1), MONDAY.isoformat(), None, None, None, False, "", self.slots[2]["id"])
        screen = self.open_grid()
        target = screen._columns()[0][0]
        screen.move_lesson(self.card(screen, self.w1), target, self.slot)
        self.assertEqual(self.saved(), [])

    def test_drag_into_busy_room_refused(self):
        with self.conn:
            self.repo.add_lesson(self.ver, self.w2, 1, 1, self.slots[2]["id"], self.r1)
        screen = self.open_grid()
        target = screen._columns()[0][0]
        screen.move_lesson(self.card(screen, self.w1), target, self.slots[2]["id"])
        self.app.update()
        self.assertEqual(self.saved(), [])
        self.dialogs()[0].destroy()

    def test_drag_to_other_class_refused(self):
        screen = self.open_grid()
        target = screen._columns()[0][1]
        screen.move_lesson(self.card(screen, self.w1), target, self.slots[2]["id"])
        self.assertEqual(self.saved(), [])

    def test_click_lesson_and_empty_cell_open_dialogs(self):
        screen = self.open_grid()
        screen.lesson_clicked(self.card(screen, self.w1), None)
        self.app.update()
        self.assertIsInstance(self.dialogs()[0], SubstitutionDialog)
        self.dialogs()[0].destroy()
        screen.cell_clicked(screen._columns()[0][0], self.slots[5]["id"])
        self.app.update()
        dialog = self.dialogs()[0]
        self.assertIsInstance(dialog, ExtraLessonDialog)
        self.assertEqual(dialog.slot.value(), self.slots[5]["id"])
        dialog.destroy()

    def test_sunday_explained(self):
        self.app.substitutions_state.date = MONDAY + datetime.timedelta(days=6)
        self.assertIsNone(self.open_grid().grid_view)


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
        dialog = SubstitutionDialog(self.app, next(r for r in self.app.current_screen.rows if r["workload_id"] == self.w1))
        dialog.room.set_value(self.r2)
        dialog.save()
        self.assertEqual(len(self.saved()), 2)

    def test_note_only_kept_and_remove(self):
        dialog = self.dialog(self.w1)
        dialog.note.insert(0, "экскурсия")
        dialog.save()
        self.app.update()
        self.assertEqual(self.saved()[0]["note"], "экскурсия")
        dialog = SubstitutionDialog(self.app, next(r for r in self.app.current_screen.rows if r["workload_id"] == self.w1))
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
        self.sub_screen.date_bar.set_week(2)
        self.app.update()
        self.assertEqual(self.app.settings.week_offset, 1 - offset)
        self.assertEqual(self.app.current_screen.rows, [])

    def test_date_navigation_and_bad_input(self):
        self.sub_screen.date_bar.set_date(MONDAY + datetime.timedelta(days=6))
        self.app.update()
        self.assertEqual(self.app.current_screen.rows, [])
        screen = self.app.current_screen
        screen.date_bar.entry.delete(0, "end")
        screen.date_bar.entry.insert(0, "вчера")
        screen.date_bar.apply_entered()
        self.assertEqual(self.app.substitutions_state.date, MONDAY + datetime.timedelta(days=6))
        screen.date_bar.entry.delete(0, "end")
        screen.date_bar.entry.insert(0, "02.11.2026")
        screen.date_bar.apply_entered()
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
