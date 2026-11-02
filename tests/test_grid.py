import tempfile
import unittest
from pathlib import Path

import openpyxl

from tests.test_schedule_ui import ScheduleCase
from tests.test_repo import RepoCase
from timetra.io.exchange import ADD, ERROR, SKIP, apply_rows, kind_by_key, parse_rows
from timetra.io.grid import read_schedule_grid, write_schedule_grid
from timetra.io.tables import HELP_SHEET, TableError
from timetra.ui.dialogs import Dialog


class GridCase(RepoCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "grid.xlsx"
        self.kind = kind_by_key("schedule")
        with self.conn:
            self.repo.save_room(None, "101", 30, 1)
            self.repo.save_room(None, "102", 30, 1)
            self.r1, self.r2 = [r["id"] for r in self.repo.rooms()]
            music = self.repo.save_subject(None, "Музыка", "", None, {5: 2})
            self.repo.save_workload(None, self.cls, music, 0, self.teacher, 1)
            english = self.repo.save_subject(None, "Английский язык", "Англ.", None, {5: 9})
            self.repo.save_workload(None, self.cls, english, 1, self.teacher, 2)
            other = self.repo.save_teacher(None, "Петрова", "Анна", "")
            self.repo.save_workload(None, self.cls, english, 2, other, 2)
        by_key = {(w["subject_name"], w["subgroup"]): w["id"] for w in self.repo.workload(self.ver)}
        self.music = by_key[("Музыка", 0)]
        self.group1, self.group2 = by_key[("Английский язык", 1)], by_key[("Английский язык", 2)]
        self.slot2 = self.repo.slots(1)[1]["id"]
        self.slot3 = self.repo.slots(1)[2]["id"]
        with self.conn:
            self.repo.add_lesson(self.ver, self.wl, 1, 1, self.slot, self.r1)
            self.repo.add_lesson(self.ver, self.wl, 2, 1, self.slot, self.r1)
            self.repo.add_lesson(self.ver, self.music, 2, 2, self.slot2, None)
            for week in (1, 2):
                self.repo.add_lesson(self.ver, self.group1, week, 3, self.slot3, self.r1)
                self.repo.add_lesson(self.ver, self.group2, week, 3, self.slot3, self.r2)

    def key(self):
        return sorted(
            (x["workload_id"], x["week_type_id"], x["weekday_id"], x["lesson_slot_id"], x["classroom_id"])
            for x in self.repo.lessons(self.ver)
        )


class WriteTest(GridCase):
    def sheet(self):
        return openpyxl.load_workbook(self.path)["Расписание"]

    def test_header_and_formatting(self):
        write_schedule_grid(self.repo, self.ver, self.path)
        sheet = self.sheet()
        self.assertEqual(sheet["A2"].value, "День")
        self.assertEqual(sheet["C2"].value, "5А")
        self.assertEqual(sheet["C3"].value, "нечётная")
        self.assertEqual(sheet["D3"].value, "чётная")
        self.assertEqual(sheet["A4"].value, "Понедельник")
        self.assertEqual(sheet.page_setup.orientation, "landscape")
        self.assertEqual(sheet["C2"].fill.fgColor.rgb[-6:], "0F6E5C")

    def test_every_week_lesson_in_merged_cell(self):
        write_schedule_grid(self.repo, self.ver, self.path)
        sheet = self.sheet()
        self.assertEqual(sheet["C4"].value, "Матем.\nИванова М. С.\nкаб. 101")
        self.assertIn("C4:D4", [str(r) for r in sheet.merged_cells.ranges])

    def test_single_week_lesson_goes_to_its_half(self):
        write_schedule_grid(self.repo, self.ver, self.path)
        sheet = self.sheet()
        row = 4 + 7 + 1  # вторник, 2 урок
        self.assertIsNone(sheet.cell(row, 3).value)
        self.assertIn("Музыка", sheet.cell(row, 4).value)

    def test_template_has_grid_without_lessons_and_help(self):
        write_schedule_grid(self.repo, self.ver, self.path, empty=True)
        book = openpyxl.load_workbook(self.path)
        self.assertIn(HELP_SHEET, book.sheetnames)
        self.assertIsNone(book["Расписание"]["C4"].value)
        self.assertEqual(read_schedule_grid(self.path)[1:], [])

    def test_no_classes_explained(self):
        with self.conn:
            self.conn.execute("DELETE FROM schedule")
            self.conn.execute("DELETE FROM workload")
            self.conn.execute("DELETE FROM classes")
        with self.assertRaisesRegex(TableError, "классы"):
            write_schedule_grid(self.repo, self.ver, self.path)

    def test_shifts_get_own_sheets(self):
        with self.conn:
            self.repo.save_class(None, 9, "А", 2, 5, None, None, None)
            self.repo.save_slot(None, 2, 1, "", "")
        write_schedule_grid(self.repo, self.ver, self.path)
        names = openpyxl.load_workbook(self.path).sheetnames
        self.assertEqual(names, ["Первая смена", "Вторая смена"])


class RoundTripTest(GridCase):
    def parse(self):
        return parse_rows(self.repo, self.kind, read_schedule_grid(self.path), self.ver)

    def test_reimport_changes_nothing(self):
        write_schedule_grid(self.repo, self.ver, self.path)
        results = self.parse()
        self.assertEqual({r.status for r in results}, {SKIP}, [r.message for r in results])

    def test_wiped_schedule_restored_from_grid(self):
        before = self.key()
        write_schedule_grid(self.repo, self.ver, self.path)
        with self.conn:
            self.repo.delete_version_lessons(self.ver)
        results = self.parse()
        self.assertEqual({r.status for r in results}, {ADD}, [r.message for r in results])
        with self.conn:
            apply_rows(self.repo, results)
        self.assertEqual(self.key(), before)

    def test_different_rooms_by_week_survive(self):
        with self.conn:
            self.repo.add_lesson(self.ver, self.music, 1, 4, self.slot, self.r1)
            self.repo.add_lesson(self.ver, self.music, 2, 4, self.slot, self.r2)
        before = self.key()
        write_schedule_grid(self.repo, self.ver, self.path)
        with self.conn:
            self.repo.delete_version_lessons(self.ver)
            apply_rows(self.repo, self.parse())
        self.assertEqual(self.key(), before)


class ReadTest(GridCase):
    def write(self, *cells):
        book = openpyxl.Workbook()
        sheet = book.active
        sheet["A1"], sheet["B1"], sheet["C1"] = "День", "Урок", "5А"
        for row in cells:
            sheet.append(row)
        book.save(self.path)

    def test_hand_written_table_without_week_halves_means_both(self):
        self.write(["Вторник", "1 урок", "Математика\nкаб. 101"])
        table = read_schedule_grid(self.path)
        self.assertEqual(table[1], ["Обе", "Вторник", "1", "5А", "Математика", "", "101"])

    def test_day_carried_down_and_groups_split(self):
        self.write(["Среда", 1, "Англ., гр. 1\nкаб. 101\n\nАнгл., гр. 2\nкаб. 102"], [None, 2, "Математика"])
        rows = read_schedule_grid(self.path)[1:]
        self.assertEqual([r[4:] for r in rows], [["Англ.", "1", "101"], ["Англ.", "2", "102"], ["Математика", "", ""]])
        self.assertEqual({r[1] for r in rows}, {"Среда"})

    def test_unknown_subject_is_row_error(self):
        self.write(["Вторник", 1, "Астрономия"])
        results = parse_rows(self.repo, self.kind, read_schedule_grid(self.path), self.ver)
        self.assertEqual(results[0].status, ERROR)

    def test_busy_room_is_row_error(self):
        self.write(["Понедельник", 1, "Музыка\nкаб. 101"])
        results = parse_rows(self.repo, self.kind, read_schedule_grid(self.path), self.ver)
        self.assertEqual(results[0].status, ERROR)
        self.assertIn("занят", results[0].message)

    def test_not_a_grid_explained(self):
        openpyxl.Workbook().save(self.path)
        with self.assertRaisesRegex(TableError, "нет сетки"):
            read_schedule_grid(self.path)

    def test_only_xlsx(self):
        with self.assertRaisesRegex(TableError, "xlsx"):
            read_schedule_grid(self.path.with_suffix(".xls"))


class GridScreenTest(ScheduleCase):
    def test_export_template_import_through_screen(self):
        self.screen.place(self.w1, self.col(self.c1), self.slot)
        state = self.app.exchange_state
        self.assertEqual(state.export_kind, "grid")
        self.app.go("exchange")
        self.app.update()
        path = self.tmp / "s.xlsx"
        self.app.current_screen.write_grid(path, False)
        with self.conn:
            self.repo.delete_version_lessons(self.ver)
        state.direction, state.import_kind = "import", "grid"
        self.app.go("exchange")
        self.app.update()
        self.app.current_screen.load_file(path)
        self.app.update()
        self.app.current_screen.apply_import()
        self.app.update()
        self.assertEqual(len(self.lessons()), 2)

    def test_error_shown_when_file_is_not_a_grid(self):
        path = self.tmp / "b.xlsx"
        openpyxl.Workbook().save(path)
        state = self.app.exchange_state
        state.direction, state.import_kind = "import", "grid"
        self.app.go("exchange")
        self.app.current_screen.load_file(path)
        self.app.update()
        dialogs = [w for w in self.app.winfo_children() if isinstance(w, Dialog)]
        self.assertEqual(len(dialogs), 1)
        dialogs[0].destroy()


if __name__ == "__main__":
    unittest.main()
