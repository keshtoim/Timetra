import tempfile
import unittest
from pathlib import Path

from tests.test_repo import RepoCase
from timetra.io.exchange import (
    ADD,
    ERROR,
    KINDS,
    SKIP,
    apply_rows,
    book_kinds,
    export_table,
    export_workbook,
    import_workbook,
    kind_by_key,
    parse_rows,
    preview_workbook,
    template_help,
    template_workbook,
    workbook_help,
)
from timetra.io.tables import HELP_SHEET, TableError, read_table, read_workbook, write_table, write_workbook

FORMATS = (".xlsx", ".xls", ".csv", ".txt")


class TablesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_roundtrip_all_formats(self):
        head, rows = ["Фамилия", "Мест"], [["Иванова", 30], ["Ёлкина", ""]]
        for suffix in FORMATS:
            path = self.dir / f"t{suffix}"
            write_table(path, head, rows)
            self.assertEqual(read_table(path)[:2], [head, ["Иванова", "30"]], suffix)
            self.assertEqual(read_table(path)[2][0], "Ёлкина", suffix)

    def test_help_goes_to_second_sheet(self):
        for suffix in (".xlsx", ".xls"):
            path = self.dir / f"h{suffix}"
            write_table(path, ["А"], [], [["Столбец"], ["А"]])
            self.assertEqual(read_table(path), [["А"]])

    def test_cp1251_csv_with_comma(self):
        path = self.dir / "c.csv"
        path.write_bytes("Фамилия,Имя\nИванова,Мария\n".encode("cp1251"))
        self.assertEqual(read_table(path), [["Фамилия", "Имя"], ["Иванова", "Мария"]])

    def test_broken_excel_gives_friendly_error(self):
        path = self.dir / "b.xlsx"
        path.write_text("не таблица", encoding="utf-8")
        with self.assertRaisesRegex(TableError, "повреждён"):
            read_table(path)

    def test_unknown_format_rejected(self):
        with self.assertRaisesRegex(TableError, "формат"):
            read_table(self.dir / "x.pdf")


class WorkbookTest(RepoCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "all.xlsx"

    def filled_sheets(self):
        # листы ссылаются друг на друга: всё новое, в базе этого ещё нет
        return {
            "кабинеты": [["Номер", "Тип"], ["301", "Обычный"]],
            "предметы": [["Название", "Балл 6"], ["Химия", "11"]],
            "учителя": [["Фамилия", "Имя", "Предметы"], ["Новикова", "Светлана", "Химия"]],
            "классы": [["Класс", "Кабинет"], ["6А", "301"]],
            "нагрузка": [["Класс", "Предмет", "Учитель", "Уроков за 2 недели"], ["6А", "Химия", "Новикова С.", "2"]],
            "расписание": [["Неделя", "День", "Номер урока", "Класс", "Предмет", "Кабинет"], ["Обе", "Вторник", "2", "6А", "Химия", "301"]],
        }

    def test_template_has_all_sheets_and_help(self):
        write_workbook(self.path, template_workbook(), workbook_help())
        sheets = read_workbook(self.path)
        self.assertEqual(list(sheets)[:-1], [k.title.lower() for k in book_kinds()])
        self.assertEqual(list(sheets)[-1], HELP_SHEET.lower())
        self.assertEqual(sheets["кабинеты"][0], ["Номер", "Тип", "Мест"])
        self.assertEqual(sheets[HELP_SHEET.lower()][0][0], "Лист")

    def test_empty_template_imports_nothing(self):
        write_workbook(self.path, template_workbook(), workbook_help())
        results = preview_workbook(self.repo, read_workbook(self.path), self.ver)
        self.assertEqual([r for _k, rows in results for r in rows], [])

    def test_preview_sees_earlier_sheets_and_rolls_back(self):
        results = preview_workbook(self.repo, self.filled_sheets(), self.ver)
        self.assertEqual({r.status for _k, rows in results for r in rows}, {ADD})
        self.assertEqual(self.repo.rooms(), [])
        self.assertEqual(len(self.repo.subjects()), 1)
        self.assertFalse(self.conn.in_transaction)

    def test_import_applies_everything_in_order(self):
        with self.conn:
            import_workbook(self.repo, self.filled_sheets(), self.ver)
        self.assertEqual(self.repo.rooms()[0]["number"], "301")
        lessons = [x for x in self.repo.lessons(self.ver) if x["class_name"] == "6А"]
        self.assertEqual(len(lessons), 2)
        self.assertEqual({x["score"] for x in lessons}, {11})

    def test_export_roundtrip_adds_nothing_new(self):
        with self.conn:
            self.repo.add_lesson(self.ver, self.wl, 1, 1, self.slot, None)
            self.repo.add_lesson(self.ver, self.wl, 2, 1, self.slot, None)
        write_workbook(self.path, export_workbook(self.repo, self.ver))
        results = preview_workbook(self.repo, read_workbook(self.path), self.ver)
        for kind, rows in results:
            self.assertNotIn(ERROR, {r.status for r in rows}, kind.key)
            if kind.key != "slots":
                self.assertNotIn(ADD, {r.status for r in rows}, kind.key)

    def test_no_known_sheets_explained(self):
        with self.assertRaisesRegex(TableError, "листов"):
            preview_workbook(self.repo, {"лист1": [["А"]]}, self.ver)

    def test_bad_sheet_named_in_error(self):
        with self.assertRaisesRegex(TableError, "Лист «Учителя»"):
            preview_workbook(self.repo, {"учителя": [["Имя"], ["Мария"]]}, self.ver)

    def test_only_xlsx_allowed(self):
        with self.assertRaisesRegex(TableError, "xlsx"):
            read_workbook(self.path.with_suffix(".csv"))
        with self.assertRaisesRegex(TableError, "xlsx"):
            write_workbook(self.path.with_suffix(".xls"), template_workbook())


class ExchangeTest(RepoCase):
    def parse(self, key, head, *rows):
        return parse_rows(self.repo, kind_by_key(key), [head, *rows], self.ver)

    def test_missing_required_column(self):
        with self.assertRaisesRegex(TableError, "Фамилия"):
            self.parse("teachers", ["Имя"], ["Мария"])

    def test_teachers_statuses(self):
        results = self.parse(
            "teachers", ["Фамилия", "Имя", "Отчество", "Предметы"],
            ["Новикова", "Светлана", "", "Математика"],
            ["Новикова", "Светлана", "", ""],
            ["", "Татьяна", "", ""],
            ["Иванова", "Мария", "Сергеевна", ""],
            ["Фёдоров", "Алексей", "", "Химия"],
        )
        self.assertEqual([r.status for r in results], [ADD, SKIP, ERROR, SKIP, ERROR])
        self.assertIn("Химия", results[4].message)
        with self.conn:
            self.assertEqual(apply_rows(self.repo, results), 1)
        added = next(t for t in self.repo.teachers() if t["last_name"] == "Новикова")
        self.assertEqual(self.repo.teacher_subject_ids(added["id"]), {self.subject})

    def test_columns_matched_by_name_in_any_order(self):
        results = self.parse("rooms", ["Мест", "Номер"], ["20", "301"])
        with self.conn:
            apply_rows(self.repo, results)
        room = self.repo.rooms()[0]
        self.assertEqual((room["number"], room["capacity"], room["type_name"]), ("301", 20, "Обычный"))

    def test_class_parsing(self):
        results = self.parse("classes", ["Класс"], ["10-б"], ["12А"], ["5а"])
        self.assertEqual([r.status for r in results], [ADD, ERROR, SKIP])
        with self.conn:
            apply_rows(self.repo, results)
        self.assertIn("10Б", [x["name"] for x in self.repo.classes()])

    def test_slots_update_time_of_existing(self):
        results = self.parse("slots", ["Номер урока", "Начало", "Конец"], ["1", "8:30", "9:15"], ["2", "10:00", "09:00"])
        self.assertEqual([r.status for r in results], [ADD, ERROR])
        with self.conn:
            apply_rows(self.repo, results)
        self.assertEqual(self.repo.slots(1)[0]["starts_at"], "08:30")
        self.assertEqual(len(self.repo.slots(1)), 7)

    def test_workload_import(self):
        with self.conn:
            other = self.repo.save_subject(None, "Музыка", "", None, {})
        head = ["Класс", "Предмет", "Учитель", "Уроков за 2 недели"]
        results = self.parse(
            "workload", head, ["5А", "Музыка", "Иванова М. С.", "2"], ["5А", "Математика", "Иванова", "10"],
            ["5А", "Музыка", "Никто", "2"],
        )
        self.assertEqual([r.status for r in results], [ADD, SKIP, ERROR])
        with self.conn:
            apply_rows(self.repo, results)
        self.assertTrue(any(w["subject_id"] == other for w in self.repo.workload(self.ver)))

    def test_schedule_import_blocks_busy_room(self):
        with self.conn:
            self.repo.save_room(None, "101", 30, 1)
            self.repo.save_class(None, 5, "Б", 1, 5, None, None, None)
            cls2 = [x["id"] for x in self.repo.classes() if x["letter"] == "Б"][0]
            self.repo.save_workload(None, cls2, self.subject, 0, self.teacher, 10)
        head = ["Неделя", "День", "Номер урока", "Класс", "Предмет", "Кабинет"]
        results = self.parse(
            "schedule", head,
            ["Обе", "Понедельник", "1", "5А", "Математика", "101"],
            ["Чётная", "Понедельник", "1", "5Б", "Математика", "101"],
            ["Нечётная", "Вторник", "1", "5Б", "Математика", "101"],
            ["Нечётная", "Вторник", "9", "5Б", "Математика", ""],
        )
        self.assertEqual([r.status for r in results], [ADD, ERROR, ADD, ERROR])
        self.assertIn("занят", results[1].message)
        with self.conn:
            apply_rows(self.repo, results)
        self.assertEqual(len(self.repo.lessons(self.ver)), 3)

    def test_export_reimports_as_already_present(self):
        with self.conn:
            self.repo.save_room(None, "101", 30, 1)
            self.repo.add_lesson(self.ver, self.wl, 1, 1, self.slot, self.repo.rooms()[0]["id"])
            self.repo.add_lesson(self.ver, self.wl, 2, 1, self.slot, self.repo.rooms()[0]["id"])
        for kind in KINDS:
            head, rows = export_table(self.repo, kind, self.ver)
            table = [head, *[[str(v) for v in r] for r in rows]]
            statuses = {r.status for r in parse_rows(self.repo, kind, table, self.ver)}
            self.assertNotIn(ERROR, statuses, kind.key)
            if kind.key != "slots":
                self.assertNotIn(ADD, statuses, kind.key)

    def test_schedule_export_merges_weeks(self):
        with self.conn:
            self.repo.add_lesson(self.ver, self.wl, 1, 1, self.slot, None)
            self.repo.add_lesson(self.ver, self.wl, 2, 1, self.slot, None)
        _head, rows = export_table(self.repo, kind_by_key("schedule"), self.ver)
        self.assertEqual([r[0] for r in rows], ["Обе"])

    def test_every_template_written_and_read_back(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            for kind in KINDS:
                head = [col.title for col in kind.columns]
                for suffix in FORMATS:
                    path = Path(tmp) / f"{kind.key}{suffix}"
                    write_table(path, head, [], template_help(kind))
                    self.assertEqual(parse_rows(self.repo, kind, read_table(path), self.ver), [])


if __name__ == "__main__":
    unittest.main()
