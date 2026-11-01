import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog

from timetra.io.exchange import ADD, ERROR, KINDS, RowResult, apply_rows, export_table, kind_by_key, parse_rows, template_help
from timetra.io.tables import TableError, read_table, write_table
from timetra.ui.dialogs import info_dialog
from timetra.ui.theme import colors as c
from timetra.ui.widgets import Btn, DataTable, Scroll, Seg, Select, badge, label, note

PREVIEW_ROWS = 6
FILE_TYPES = [
    ("Excel (.xlsx)", "*.xlsx"), ("Excel 97-2003 (.xls)", "*.xls"),
    ("Таблица CSV (.csv)", "*.csv"), ("Текст (.txt)", "*.txt"),
]
FORMATS = [
    (".xlsx", ".xlsx", "Файл Excel, подходит в большинстве случаев"), (".xls", ".xls", "Для старых версий Excel"),
    (".csv", ".csv", "Простая таблица для других программ"), (".txt", ".txt", "Обычный текст"),
]


@dataclass
class ExchangeState:
    direction: str = "export"
    export_kind: str = "schedule"
    import_kind: str = "teachers"
    fmt: str = ".xlsx"
    results: list[RowResult] | None = None
    file_name: str = ""


class ExchangeScreen(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=c["bg"])
        self.app = app
        self.repo = app.repo
        self.state = app.exchange_state
        label(self, "Импорт и экспорт", 15, True, anchor="w").pack(fill="x")
        label(self, "Сохраните данные в файл или загрузите их из таблицы, которая у вас уже есть.", color="muted", anchor="w").pack(fill="x", pady=(0, 10))
        Seg(
            self, [("export", "Сохранить в файл"), ("import", "Загрузить из файла")],
            self.state.direction, self._set_direction,
        ).pack(anchor="w", pady=(0, 10))
        if self.state.direction == "export":
            self._build_export()
        else:
            self._build_import()

    def _set_direction(self, value):
        self.state.direction = value
        self.state.results = None
        self.app.refresh()

    def _card(self):
        card = tk.Frame(self, bg=c["surface"], highlightthickness=1, highlightbackground=c["border"], padx=12, pady=10)
        card.pack(fill="x", pady=(0, 10))
        return card

    def _build_export(self):
        s = self.state
        kind = kind_by_key(s.export_kind)
        card = self._card()
        row = tk.Frame(card, bg=c["surface"])
        row.pack(fill="x")
        label(row, "Что сохранить", 9, color="muted", bg="surface").pack(side="left", padx=(0, 6))
        Select(row, [(k.key, k.title) for k in KINDS], s.export_kind, self._set_export_kind, width=16).pack(side="left")
        label(row, "Формат файла", 9, color="muted", bg="surface").pack(side="left", padx=(14, 6))
        Seg(row, FORMATS, s.fmt, self._set_format).pack(side="left")
        Btn(row, "Сохранить файл", "save", self.save_export, "primary").pack(side="left", padx=(14, 0))
        head, rows = export_table(self.repo, kind, self.app.version_id)
        label(card, f"Так будет выглядеть файл. Всего строк: {len(rows)}", 9, color="muted", bg="surface", anchor="w").pack(fill="x", pady=(8, 0))
        scroll = Scroll(self, horizontal=True)
        scroll.pack(fill="both", expand=True)
        if rows:
            preview = [{"id": i, "cells": list(r)} for i, r in enumerate(rows[:PREVIEW_ROWS])]
            DataTable(scroll.inner, head, preview).pack(fill="x", anchor="w")
        else:
            label(scroll.inner, "Пока нечего сохранять: здесь нет данных.", color="muted").pack(anchor="w", pady=10)

    def _set_export_kind(self, value):
        self.state.export_kind = value
        self.app.refresh()

    def _set_format(self, value):
        self.state.fmt = value
        self.app.refresh()

    def save_export(self):
        kind = kind_by_key(self.state.export_kind)
        path = filedialog.asksaveasfilename(
            parent=self.app, title="Куда сохранить файл", defaultextension=self.state.fmt,
            initialfile=f"{kind.title}{self.state.fmt}", filetypes=self._file_types_first(self.state.fmt),
        )
        if path:
            self._write(Path(path), *export_table(self.repo, kind, self.app.version_id))

    def _write(self, path, head, rows, help_rows=None):
        try:
            write_table(path, head, rows, help_rows)
        except TableError as error:
            info_dialog(self.app, "Не удалось сохранить", str(error))
            return
        self.app.toast(f"Файл сохранён: {path.name}")

    def _file_types_first(self, fmt):
        return sorted(FILE_TYPES, key=lambda t: t[1] != f"*{fmt}")

    def _build_import(self):
        s = self.state
        card = self._card()
        row = tk.Frame(card, bg=c["surface"])
        row.pack(fill="x")
        label(row, "Что загрузить", 9, color="muted", bg="surface").pack(side="left", padx=(0, 6))
        Select(row, [(k.key, k.title) for k in KINDS], s.import_kind, self._set_import_kind, width=16).pack(side="left")
        Btn(
            row, "Скачать шаблон", "download", self.save_template,
            tooltip="Сохранить пустую таблицу с нужными столбцами. В Excel на втором листе есть пояснения",
        ).pack(side="left", padx=(14, 0))
        Btn(
            row, "Выбрать файл", "upload", self.choose_file,
            tooltip="Подойдут файлы .xlsx, .xls, .csv и .txt",
        ).pack(side="left", padx=(8, 0))
        if s.results is None:
            label(
                card, "Заполните шаблон и загрузите его. Порядок: сначала кабинеты и предметы, потом учителя и классы, затем нагрузка и расписание.",
                9, color="muted", bg="surface", anchor="w", wraplength=800, justify="left",
            ).pack(fill="x", pady=(8, 0))
            return
        self._build_preview(card)

    def _set_import_kind(self, value):
        self.state.import_kind = value
        self.state.results = None
        self.app.refresh()

    def save_template(self):
        kind = kind_by_key(self.state.import_kind)
        path = filedialog.asksaveasfilename(
            parent=self.app, title="Куда сохранить шаблон", defaultextension=".xlsx",
            initialfile=f"Шаблон - {kind.title}.xlsx", filetypes=FILE_TYPES,
        )
        if path:
            self._write(Path(path), [col.title for col in kind.columns], [], template_help(kind))

    def choose_file(self):
        path = filedialog.askopenfilename(
            parent=self.app, title="Выберите файл",
            filetypes=[("Таблицы", "*.xlsx *.xls *.csv *.txt"), *FILE_TYPES],
        )
        if path:
            self.load_file(Path(path))

    def load_file(self, path: Path):
        kind = kind_by_key(self.state.import_kind)
        try:
            results = parse_rows(self.repo, kind, read_table(path), self.app.version_id)
        except TableError as error:
            info_dialog(self.app, "Не удалось прочитать файл", str(error))
            return
        self.state.results = results
        self.state.file_name = path.name
        self.app.refresh()

    def _build_preview(self, card):
        s = self.state
        results = s.results
        ready = sum(r.status == ADD for r in results)
        errors = sum(r.status == ERROR for r in results)
        row = tk.Frame(card, bg=c["surface"])
        row.pack(fill="x", pady=(8, 0))
        label(row, s.file_name, bg="surface").pack(side="left", padx=(0, 10))
        Btn(row, "Отмена", None, self.cancel_import).pack(side="right")
        Btn(row, f"Загрузить строк: {ready}", "check", self.apply_import, "primary", disabled=not ready).pack(side="right", padx=(0, 8))
        if errors:
            text = f"Строк с ошибками: {errors}. Они не будут загружены. Исправьте их в файле и загрузите файл ещё раз."
            note(card, text, "warning").pack(fill="x", pady=(8, 0))
        elif not results:
            note(card, "В файле нет строк с данными, только заголовок.", "neutral").pack(fill="x", pady=(8, 0))
        if not results:
            return
        kind = kind_by_key(s.import_kind)
        head = [col.title for col in kind.columns]
        filled = [i for i in range(len(head)) if any(r.values[i] for r in results)]
        scroll = Scroll(self, horizontal=True)
        scroll.pack(fill="both", expand=True)
        rows = []
        for i, r in enumerate(results):
            status = {ADD: "ok", ERROR: "conflict"}.get(r.status, "warning")
            cells = [r.values[n] for n in filled]
            cells.append(lambda parent, t=r.message, k=status: badge(parent, t, k))
            rows.append({"id": i, "cells": cells})
        DataTable(scroll.inner, [*[head[n] for n in filled], "Результат"], rows).pack(fill="x", anchor="w")

    def cancel_import(self):
        self.state.results = None
        self.app.refresh()

    def apply_import(self):
        results, self.state.results = self.state.results, None
        count = [0]

        def action():
            count[0] = apply_rows(self.repo, results)

        if self.app.mutate("Данные загружены", action):
            self.app.toast(f"Загружено строк: {count[0]}", can_undo=True)
