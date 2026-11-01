import unittest

from tests.test_ui import UiCase
from timetra.io.exchange import KINDS
from timetra.io.tables import write_table, write_workbook
from timetra.services.checks import find_problems
from timetra.ui.dialogs import Dialog
from timetra.ui.schedule_screen import ComposeDialog, LessonDialog


class ScheduleCase(UiCase):
    def setUp(self):
        super().setUp()
        repo = self.repo = self.app.repo
        self.t1 = repo.save_teacher(None, "Иванова", "Мария", "")
        self.t2 = repo.save_teacher(None, "Петрова", "Анна", "")
        self.s1 = repo.save_subject(None, "Математика", "Матем.", None, {5: 10})
        self.s2 = repo.save_subject(None, "Музыка", "", None, {5: 2})
        repo.save_room(None, "101", 30, 1)
        repo.save_room(None, "102", 30, 1)
        self.r1, self.r2 = [r["id"] for r in repo.rooms()]
        repo.save_class(None, 5, "А", 1, 5, 26, None, self.r1)
        repo.save_class(None, 5, "Б", 1, 5, 24, None, None)
        self.c1, self.c2 = [x["id"] for x in repo.classes()]
        self.ver = self.app.version_id
        repo.save_workload(None, self.c1, self.s1, 0, self.t1, 4)
        repo.save_workload(None, self.c2, self.s1, 0, self.t1, 4)
        repo.save_workload(None, self.c2, self.s2, 0, self.t2, 2)
        self.conn.commit()
        self.w1, self.w2, self.w3 = [
            next(w["id"] for w in repo.workload(self.ver) if w["class_id"] == c and w["subject_id"] == s)
            for c, s in ((self.c1, self.s1), (self.c2, self.s1), (self.c2, self.s2))
        ]
        self.slots = repo.slots(1)
        self.slot = self.slots[0]["id"]
        self.reload()

    def reload(self):
        self.app.go("schedule")
        self.app.update()
        self.screen = self.app.current_screen

    def col(self, class_id=None, room_id=None, teacher_id=None, day=1):
        from timetra.ui.schedule_grid import Column

        return Column("", "", day, class_id=class_id, room_id=room_id, teacher_id=teacher_id)

    def lessons(self):
        return self.repo.lessons(self.ver)

    def dialogs(self):
        return [w for w in self.app.winfo_children() if isinstance(w, Dialog)]


class PlaceTest(ScheduleCase):
    def test_all_views_render(self):
        for view in ("classes", "week", "teachers", "rooms"):
            self.screen._set("view", view)
            self.app.update()
            self.assertIsNotNone(self.app.current_screen.grid_view)

    def test_place_on_both_weeks_with_home_room(self):
        self.screen.place(self.w1, self.col(self.c1), self.slot)
        rows = self.lessons()
        self.assertEqual({r["week_type_id"] for r in rows}, {1, 2})
        self.assertEqual({r["classroom_id"] for r in rows}, {self.r1})

    def test_place_one_week_when_both_off(self):
        self.app.schedule_state.both = False
        self.screen.place(self.w1, self.col(self.c1), self.slot)
        self.assertEqual([r["week_type_id"] for r in self.lessons()], [1])

    def test_wrong_class_column_refused(self):
        self.screen.place(self.w1, self.col(self.c2), self.slot)
        self.assertEqual(self.lessons(), [])

    def test_busy_teacher_placed_with_warning(self):
        self.screen.place(self.w1, self.col(self.c1), self.slot)
        self.reload()
        self.screen.place(self.w2, self.col(self.c2), self.slot)
        self.assertEqual(len(self.lessons()), 4)
        self.reload()
        self.assertTrue(any("два урока" in p.title for p in self.screen.problems))

    def test_busy_room_refused_in_room_view(self):
        self.screen.place(self.w1, self.col(room_id=self.r2), self.slot)
        self.reload()
        before = len(self.lessons())
        self.screen.place(self.w3, self.col(room_id=self.r2), self.slot)
        self.app.update()
        self.assertEqual(len(self.lessons()), before)
        self.assertEqual(len(self.dialogs()), 1)
        self.dialogs()[0].destroy()

    def test_over_limit_refused(self):
        self.screen.place(self.w3, self.col(self.c2), self.slot)
        self.reload()
        self.screen.place(self.w3, self.col(self.c2), self.slots[1]["id"])
        self.assertEqual(len(self.lessons()), 2)

    def test_undo_after_place(self):
        self.screen.place(self.w1, self.col(self.c1), self.slot)
        self.app.undo()
        self.assertEqual(self.lessons(), [])


class MoveTest(ScheduleCase):
    def setUp(self):
        super().setUp()
        self.screen.place(self.w1, self.col(self.c1), self.slot)
        self.reload()

    def test_move_keeps_twin_together(self):
        self.screen.move_lesson(self.lessons()[0], self.col(self.c1, day=2), self.slots[1]["id"])
        self.assertEqual({(r["weekday_id"], r["lesson_slot_id"]) for r in self.lessons()}, {(2, self.slots[1]["id"])})

    def test_move_to_other_class_refused(self):
        self.screen.move_lesson(self.lessons()[0], self.col(self.c2, day=2), self.slot)
        self.assertEqual(self.lessons()[0]["weekday_id"], 1)

    def test_move_into_busy_room_refused(self):
        with self.conn:
            self.repo.add_lesson(self.ver, self.w3, 1, 2, self.slot, self.r1)
        self.screen.move_lesson(self.lessons()[0], self.col(self.c1, day=2), self.slot)
        self.app.update()
        self.assertTrue(all(r["weekday_id"] == 1 for r in self.lessons() if r["workload_id"] == self.w1))
        self.dialogs()[0].destroy()


class PickAndGridTest(ScheduleCase):
    def test_cell_states(self):
        self.screen.place(self.w1, self.col(self.c1), self.slot)
        self.app.schedule_state.pick = self.w2
        self.reload()
        self.assertEqual(self.screen.cell_state(self.col(self.c2), self.slot)[0], "warn")
        self.assertEqual(self.screen.cell_state(self.col(self.c2), self.slots[1]["id"])[0], "free")
        self.assertEqual(self.screen.cell_state(self.col(self.c1), self.slot)[0], None)

    def test_grid_hit_testing_and_click_opens_dialog(self):
        self.screen.place(self.w1, self.col(self.c1), self.slot)
        self.reload()
        grid = self.screen.grid_view
        self.app.update()
        x1, y1, x2, y2, lesson = grid.cards[0]
        self.assertEqual(grid.card_at(x1 + 2, y1 + 2)["id"], lesson["id"])
        self.assertEqual(grid.cell_at(x1 + 2, y1 + 2)[1], self.slot)
        self.screen.lesson_clicked(lesson, None)
        self.app.update()
        dialog = self.dialogs()[0]
        self.assertIsInstance(dialog, LessonDialog)
        dialog.destroy()

    def test_pick_click_places(self):
        self.app.schedule_state.pick = self.w1
        self.reload()
        self.screen.cell_clicked(self.col(self.c1), self.slot)
        self.assertEqual(len(self.lessons()), 2)
        self.assertEqual(self.app.schedule_state.pick, self.w1)

    def test_auto_and_copy_version(self):
        self.screen.compose(False, "even")
        self.app.update()
        self.assertEqual(self.repo.conflict_pairs(self.ver), [])
        self.assertEqual(len(self.lessons()), 10)
        self.dialogs()[0].destroy()

    def test_compose_dialog_rebuild_replaces_lessons_and_undo_restores(self):
        with self.conn:
            self.repo.add_lesson(self.ver, self.w1, 1, 5, self.slots[6]["id"], None)
        self.reload()
        dialog = ComposeDialog(self.screen)
        dialog.mode.set_value(True)
        dialog.update_notes()
        dialog.run()
        self.app.update()
        self.assertFalse(any(r["lesson_slot_id"] == self.slots[6]["id"] for r in self.lessons()))
        self.assertEqual(len(self.lessons()), 10)
        self.dialogs()[0].destroy()
        self.app.undo()
        self.assertEqual(len(self.lessons()), 1)


class WholeScheduleTest(ScheduleCase):
    def open_all(self):
        self.app.schedule_state.view = "all"
        self.reload()
        self.app.update()
        return self.screen.grid_view

    def test_rows_cover_every_day_and_lesson(self):
        grid = self.open_all()
        self.assertEqual(len(grid.rows), 5 * len(self.slots))
        col, slot_id, _i, r = grid.cell_at(1, grid.row_tops[len(self.slots)] + 1)
        self.assertEqual((col.day, slot_id, r), (2, self.slot, len(self.slots)))

    def test_same_lesson_on_both_weeks_is_one_card(self):
        self.screen.place(self.w1, self.col(self.c1, day=3), self.slot)
        grid = self.open_all()
        self.assertEqual(len(grid.cards), 1)
        lesson = grid.cards[0][4]
        self.assertEqual(grid.cell_at(grid.cards[0][0] + 1, grid.cards[0][1] + 1)[0].day, 3)
        self.assertIsNotNone(self.repo.lesson_twin(lesson))

    def test_different_weeks_split_cell_in_halves(self):
        with self.conn:
            self.repo.add_lesson(self.ver, self.w2, 1, 1, self.slot, None)
            self.repo.add_lesson(self.ver, self.w3, 2, 1, self.slot, None)
        grid = self.open_all()
        self.assertEqual(len(grid.cards), 2)
        (ox1, _a, ox2, _b, odd), (ex1, _c, ex2, _d, even) = sorted(grid.cards, key=lambda x: x[0])
        self.assertEqual((odd["week_type_id"], even["week_type_id"]), (1, 2))
        self.assertLess(ox2, ex1)
        self.assertEqual(grid.week_at(ox1 + 1), 1)
        self.assertEqual(grid.week_at(ex2 - 1), 2)

    def test_different_rooms_stay_separate(self):
        with self.conn:
            self.repo.add_lesson(self.ver, self.w1, 1, 1, self.slot, self.r1)
            self.repo.add_lesson(self.ver, self.w1, 2, 1, self.slot, self.r2)
        self.assertEqual(len(self.open_all().cards), 2)

    def test_move_from_whole_view_uses_row_day(self):
        self.screen.place(self.w1, self.col(self.c1), self.slot)
        grid = self.open_all()
        target = grid.cell_at(grid.cards[0][0] + 1, grid.row_tops[len(self.slots) + 1] + 1)
        self.screen.move_lesson(grid.cards[0][4], target[0], target[1])
        self.assertEqual({(r["weekday_id"], r["lesson_slot_id"]) for r in self.lessons()}, {(2, self.slots[1]["id"])})

    def test_conflict_on_twin_marks_merged_card(self):
        with self.conn:
            self.repo.add_lesson(self.ver, self.w1, 1, 1, self.slot, None)
            self.repo.add_lesson(self.ver, self.w1, 2, 1, self.slot, None)
            self.repo.add_lesson(self.ver, self.w2, 2, 1, self.slot, None)
        grid = self.open_all()
        merged = next(x for x in grid.cards if x[4]["workload_id"] == self.w1)
        self.assertIsNotNone(grid._level(merged[4], self.repo.lesson_twin(merged[4])))


class CheckAndHelpTest(ScheduleCase):
    def test_show_problem_jumps_to_schedule(self):
        with self.conn:
            self.repo.add_lesson(self.ver, self.w1, 2, 3, self.slots[2]["id"], None)
            self.repo.add_lesson(self.ver, self.w2, 2, 3, self.slots[2]["id"], None)
        self.app.go("check")
        self.app.update()
        screen = self.app.current_screen
        problem = find_problems(self.repo, self.ver)[0]
        screen.show(problem)
        self.app.update()
        state = self.app.schedule_state
        self.assertEqual((self.app.screen, state.day, state.week), ("schedule", 3, 2))
        self.assertEqual(len(state.flash), 2)
        screen._clear_flash()
        self.assertEqual(state.flash, set())

    def test_help_shows_with_empty_and_filled_data(self):
        self.app.go("help")
        self.app.update()
        self.screen.compose(False, "even")
        self.dialogs()[0].destroy()
        self.app.go("help")
        self.app.update()


class ExchangeUiTest(ScheduleCase):
    def open_import(self, kind):
        state = self.app.exchange_state
        state.direction, state.import_kind = "import", kind
        self.app.go("exchange")
        self.app.update()
        return self.app.current_screen

    def test_export_preview_for_every_kind(self):
        for kind in KINDS:
            self.app.exchange_state.export_kind = kind.key
            self.app.go("exchange")
            self.app.update()

    def test_import_preview_then_apply_and_undo(self):
        path = self.tmp / "t.xlsx"
        write_table(path, ["Фамилия", "Имя"], [["Новикова", "Светлана"], ["", "Без фамилии"]])
        screen = self.open_import("teachers")
        screen.load_file(path)
        self.app.update()
        self.assertEqual(len(self.app.exchange_state.results[0][1]), 2)
        self.app.current_screen.apply_import()
        self.app.update()
        self.assertIn("Новикова", [t["last_name"] for t in self.repo.teachers()])
        self.assertIsNone(self.app.exchange_state.results)
        self.app.undo()
        self.assertNotIn("Новикова", [t["last_name"] for t in self.repo.teachers()])

    def test_bad_file_explained(self):
        path = self.tmp / "b.csv"
        path.write_text("Что-то;Другое\n1;2\n", encoding="utf-8")
        self.open_import("teachers").load_file(path)
        self.app.update()
        self.assertIsNone(self.app.exchange_state.results)
        self.assertEqual(len(self.dialogs()), 1)
        self.dialogs()[0].destroy()

    def test_header_only_template_shows_note(self):
        path = self.tmp / "e.xlsx"
        write_table(path, ["Фамилия", "Имя"], [])
        self.open_import("teachers").load_file(path)
        self.app.update()
        self.assertEqual(self.app.exchange_state.results[0][1], [])

    def test_all_in_one_file_preview_apply_undo(self):
        path = self.tmp / "all.xlsx"
        write_workbook(path, [
            ("Кабинеты", ["Номер"], [["301"]]),
            ("Предметы", ["Название"], [["Химия"]]),
            ("Учителя", ["Фамилия", "Имя", "Предметы"], [["Новикова", "Светлана", "Химия"]]),
        ])
        self.app.exchange_state.export_kind = "all"
        self.app.go("exchange")
        self.app.update()
        screen = self.open_import("all")
        screen.load_file(path)
        self.app.update()
        self.assertEqual(len(self.app.exchange_state.results), 3)
        self.assertNotIn("301", [r["number"] for r in self.repo.rooms()])
        self.app.current_screen.apply_import()
        self.app.update()
        self.assertIn("301", [r["number"] for r in self.repo.rooms()])
        self.app.undo()
        self.assertNotIn("301", [r["number"] for r in self.repo.rooms()])

    def test_single_kind_takes_its_sheet_from_shared_file(self):
        path = self.tmp / "all.xlsx"
        write_workbook(path, [("Кабинеты", ["Номер"], [["301"]]), ("Учителя", ["Фамилия", "Имя"], [["Новикова", "Светлана"]])])
        self.open_import("teachers").load_file(path)
        self.app.update()
        self.assertEqual(self.app.exchange_state.results[0][1][0].values[0], "Новикова")


class LessonDialogTest(ScheduleCase):
    def test_new_lesson_saved(self):
        dialog = LessonDialog(self.screen, col=self.col(self.c1), slot_id=self.slot)
        dialog.save()
        self.app.update()
        self.assertEqual(len(self.lessons()), 2)

    def test_busy_room_blocks_save_but_busy_teacher_does_not(self):
        with self.conn:
            self.repo.add_lesson(self.ver, self.w2, 1, 1, self.slot, self.r1)
            self.repo.add_lesson(self.ver, self.w2, 2, 1, self.slot, self.r1)
        self.reload()
        dialog = LessonDialog(self.screen, col=self.col(self.c1), slot_id=self.slot)
        dialog.room_select.set_value(self.r1)
        dialog.update_notes()
        dialog.save()
        self.app.update()
        self.assertTrue(dialog.winfo_exists())
        self.assertEqual(len(self.lessons()), 2)
        dialog.room_select.set_value(self.r2)
        dialog.save()
        self.app.update()
        self.assertEqual(len(self.lessons()), 4)

    def test_edit_room_and_remove(self):
        self.screen.place(self.w1, self.col(self.c1), self.slot)
        self.reload()
        dialog = LessonDialog(self.screen, lesson=self.lessons()[0])
        dialog.room_select.set_value(self.r2)
        dialog.save()
        self.app.update()
        self.assertEqual({r["classroom_id"] for r in self.lessons()}, {self.r2})
        self.reload()
        dialog = LessonDialog(self.screen, lesson=self.lessons()[0])
        dialog.remove()
        self.app.update()
        self.assertEqual(self.lessons(), [])

    def test_no_candidates_explained(self):
        self.screen.place(self.w3, self.col(self.c2), self.slot)
        self.reload()
        LessonDialog(self.screen, col=self.col(teacher_id=self.t2), slot_id=self.slots[1]["id"])
        self.app.update()
        self.assertEqual(len(self.dialogs()), 1)
        self.dialogs()[0].destroy()


if __name__ == "__main__":
    unittest.main()
