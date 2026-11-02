import datetime
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog

from timetra.io.tables import TableError, write_table
from timetra.services.substitutions import (
    DATE_FORMAT,
    EXPORT_HEAD,
    SUNDAY,
    check_substitution,
    day_lessons,
    describe_change,
    export_rows,
    free_teacher_ids,
    parse_date,
    week_for_date,
)
from timetra.ui.dialogs import Dialog, info_dialog
from timetra.ui.theme import colors as c
from timetra.ui.theme import font
from timetra.ui.widgets import Btn, DataTable, Scroll, Seg, Select, badge, label, note

ODD, EVEN = 1, 2
ONE_DAY = datetime.timedelta(days=1)
XLSX_ONLY = [("Excel (.xlsx)", "*.xlsx")]


@dataclass
class SubstitutionsState:
    date: datetime.date = field(default_factory=datetime.date.today)
    teacher_id: int | None = None
    class_id: int | None = None
    only_changed: bool = False


class SubstitutionsScreen(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=c["bg"])
        self.app = app
        self.repo = app.repo
        self.state = app.substitutions_state
        # замены относятся к настоящему расписанию, а не к черновику, открытому на другом экране
        self.version = self.repo.active_version_id()
        self.offset = app.settings.week_offset
        self.rows = day_lessons(self.repo, self.version, self.state.date, self.offset)
        self._build_head()
        self._build_tools()
        self._build_table()

    def _build_head(self):
        row = tk.Frame(self, bg=c["bg"])
        row.pack(fill="x", pady=(0, 8))
        titles = tk.Frame(row, bg=c["bg"])
        titles.pack(side="left")
        label(titles, "Замены", 15, True, anchor="w").pack(fill="x")
        version = next(v["name"] for v in self.repo.versions() if v["id"] == self.version)
        label(titles, f"Изменения только на выбранный день. Основа — действующий вариант «{version}».", color="muted", anchor="w").pack(fill="x")
        Btn(
            row, "Сохранить замены в файл", "save", self.save_file,
            tooltip="Файл Excel со всеми заменами этого дня, например для печати",
            disabled=not any(r["substitution_id"] for r in self.rows),
        ).pack(side="right")
        Btn(row, "Отменить", "undo", self.app.undo, disabled=not self.app.undo_stack, tooltip="Вернуть как было до последнего изменения").pack(side="right", padx=8)

    def _build_tools(self):
        s = self.state
        box = tk.Frame(self, bg=c["surface"], highlightthickness=1, highlightbackground=c["border"], padx=10, pady=8)
        box.pack(fill="x", pady=(0, 8))
        first = tk.Frame(box, bg=c["surface"])
        first.pack(fill="x", pady=2)
        label(first, "Дата", 9, color="muted", bg="surface").pack(side="left", padx=(0, 6))
        Btn(first, "Назад", "collapse", lambda: self.set_date(s.date - ONE_DAY), tooltip="Предыдущий день").pack(side="left")
        self.date_entry = tk.Entry(
            first, font=font(11, True), bg=c["surface"], fg=c["text"], insertbackground=c["text"], relief="flat", justify="center",
            highlightthickness=1, highlightbackground=c["border"], highlightcolor=c["accent"], width=11,
        )
        self.date_entry.insert(0, s.date.strftime(DATE_FORMAT))
        self.date_entry.pack(side="left", padx=6, ipady=3)
        self.date_entry.bind("<Return>", lambda _e: self.apply_entered_date())
        self.date_entry.bind("<FocusOut>", lambda _e: self.apply_entered_date())
        Btn(first, "Вперёд", "expand", lambda: self.set_date(s.date + ONE_DAY), tooltip="Следующий день").pack(side="left")
        Btn(first, "Сегодня", None, lambda: self.set_date(datetime.date.today())).pack(side="left", padx=(6, 14))
        days = {d["id"]: d["name"] for d in self.repo.weekdays()}
        day_name = days.get(s.date.isoweekday(), "Воскресенье")
        label(first, day_name, 11, True, bg="surface").pack(side="left", padx=(0, 14))
        label(first, "Неделя", 9, color="muted", bg="surface").pack(side="left", padx=(0, 6))
        Seg(
            first, [(ODD, "Нечётная", "Если неделя определилась неверно, нажмите правильную: программа запомнит"), (EVEN, "Чётная", "Если неделя определилась неверно, нажмите правильную: программа запомнит")],
            week_for_date(s.date, self.offset), self.set_week,
        ).pack(side="left")

        second = tk.Frame(box, bg=c["surface"])
        second.pack(fill="x", pady=2)
        label(second, "Учитель", 9, color="muted", bg="surface").pack(side="left", padx=(0, 6))
        teachers = [(None, "Все учителя"), *[(t["id"], t["short"]) for t in self.repo.teachers()]]
        Select(
            second, teachers, s.teacher_id, lambda v: self._set("teacher_id", v), width=22,
            tooltip="Заболел учитель? Выберите его и увидите все уроки, которые нужно заменить",
        ).pack(side="left", padx=(0, 14))
        label(second, "Класс", 9, color="muted", bg="surface").pack(side="left", padx=(0, 6))
        classes = [(None, "Все классы"), *[(x["id"], x["name"]) for x in self.repo.classes()]]
        Select(second, classes, s.class_id, lambda v: self._set("class_id", v), width=12).pack(side="left", padx=(0, 14))
        Seg(second, [(False, "Все уроки"), (True, "Только замены")], s.only_changed, lambda v: self._set("only_changed", v)).pack(side="left")

    def _set(self, name, value):
        setattr(self.state, name, value)
        self.app.refresh()

    def set_date(self, date):
        self.state.date = date
        self.app.refresh()

    def apply_entered_date(self):
        if not self.date_entry.winfo_exists():
            return
        text = self.date_entry.get()
        date = parse_date(text)
        if date is None:
            self.date_entry.delete(0, "end")
            self.date_entry.insert(0, self.state.date.strftime(DATE_FORMAT))
            self.app.toast("Укажите дату так: 02.11.2026")
        elif date != self.state.date:
            self.set_date(date)

    def set_week(self, week):
        if week == week_for_date(self.state.date, self.offset):
            return
        self.app.settings.week_offset = 1 - self.offset
        self.app.settings_changed(rebuild=False)
        self.app.refresh()
        self.app.toast("Запомнил: чётность недель переключена для всех дат")

    def _visible_rows(self):
        s = self.state
        result = []
        for row in self.rows:
            if s.teacher_id and s.teacher_id not in (row["base_teacher_id"], row["eff_teacher_id"]):
                continue
            if s.class_id and row["class_id"] != s.class_id:
                continue
            if s.only_changed and not row["substitution_id"]:
                continue
            result.append(row)
        return result

    def _build_table(self):
        scroll = Scroll(self)
        scroll.pack(fill="both", expand=True)
        if self.state.date.isoweekday() == SUNDAY:
            label(scroll.inner, "Воскресенье: уроков нет.", color="muted").pack(anchor="w", pady=20)
            return
        rows = self._visible_rows()
        if not rows:
            text = "Нет уроков под выбранные условия." if self.rows else "В этот день в действующем варианте нет уроков."
            label(scroll.inner, text, color="muted").pack(anchor="w", pady=20)
            return
        table_rows = [self._table_row(r) for r in rows]
        columns = ["Класс", "Урок", "Предмет", "Учитель", "Кабинет", "Замена"]
        DataTable(scroll.inner, columns, table_rows, [("Заменить", "edit", self.edit)]).pack(fill="x")

    def _table_row(self, row):
        group = f" (гр. {row['subgroup']})" if row["subgroup"] else ""
        change = describe_change(row)
        if row["note"]:
            change = f"{change} ({row['note']})" if change else row["note"]
        kind = "conflict" if row["is_cancelled"] else "warning"
        cell = (lambda parent, t=change, k=kind: badge(parent, t, k)) if change else ""
        return {
            "id": row["lesson_id"],
            "cells": [row["class_name"], row["lesson_number"], row["base_subject"] + group, row["base_teacher"], row["base_room"], cell],
        }

    def edit(self, lesson_id):
        row = next(r for r in self.rows if r["lesson_id"] == lesson_id)
        SubstitutionDialog(self, row)

    def save_file(self):
        date = self.state.date.strftime(DATE_FORMAT)
        path = filedialog.asksaveasfilename(
            parent=self.app, title="Куда сохранить замены", defaultextension=".xlsx",
            initialfile=f"Замены {date}.xlsx", filetypes=XLSX_ONLY,
        )
        if path:
            self.write_file(Path(path))

    def write_file(self, path: Path):
        try:
            write_table(path, EXPORT_HEAD, export_rows(self.rows))
        except TableError as error:
            info_dialog(self.app, "Не удалось сохранить", str(error))
            return
        self.app.toast(f"Файл сохранён: {path.name}")


class SubstitutionDialog(Dialog):
    def __init__(self, screen, row):
        self.screen = screen
        self.repo = screen.repo
        self.row = row
        super().__init__(screen.app, "Замена урока")
        date = screen.state.date.strftime(DATE_FORMAT)
        group = f" (гр. {row['subgroup']})" if row["subgroup"] else ""
        text = f"{date}, {row['lesson_number']} урок, {row['class_name']}. По расписанию: {row['base_subject']}{group}, {row['base_teacher']}"
        label(self.body, text, 9, color="muted", bg="surface", anchor="w", wraplength=440, justify="left").pack(fill="x", pady=(0, 8))

        free = free_teacher_ids(self.repo, screen.version, screen.state.date, screen.offset, row)
        teachers = sorted(self.repo.teachers(), key=lambda t: (t["id"] not in free, t["short"]))
        self.teacher = self._select("Кто ведёт", [(t["id"], f"{t['short']}{'' if t['id'] in free else ' (занят)'}") for t in teachers], row["eff_teacher_id"])
        self.subject = self._select("Предмет", [(s["id"], s["name"]) for s in self.repo.subjects()], row["eff_subject_id"])
        self.room = self._select(
            "Кабинет", [(None, "Без кабинета"), *[(r["id"], f"{r['number']} ({r['type_name']})") for r in self.repo.rooms()]], row["eff_room_id"],
        )
        self.cancelled = tk.BooleanVar(value=bool(row["is_cancelled"]))
        tk.Checkbutton(
            self.body, text="Урока не будет", variable=self.cancelled, command=self.update_notes, font=font(), bg=c["surface"],
            fg=c["text"], selectcolor=c["surface"], activebackground=c["surface"], activeforeground=c["text"], anchor="w",
        ).pack(fill="x", pady=(0, 6))
        label(self.body, "Примечание", 9, color="muted", bg="surface", anchor="w").pack(fill="x")
        self.note = tk.Entry(
            self.body, font=font(), bg=c["surface"], fg=c["text"], insertbackground=c["text"], relief="flat",
            highlightthickness=1, highlightbackground=c["border"], highlightcolor=c["accent"],
        )
        self.note.insert(0, row["note"] or "")
        self.note.pack(fill="x", ipady=3, pady=(0, 8))
        self.notes = tk.Frame(self.body, bg=c["surface"])
        self.notes.pack(fill="x")
        buttons = self.footer()
        Btn(buttons, "Сохранить", "check", self.save, "primary").pack(side="right")
        Btn(buttons, "Отмена", None, self.destroy).pack(side="right", padx=(0, 8))
        if row["substitution_id"]:
            Btn(buttons, "Убрать замену", "delete", self.remove, "danger").pack(side="left")
        self.update_notes()
        self.show()

    def _select(self, title, items, value):
        label(self.body, title, 9, color="muted", bg="surface", anchor="w").pack(fill="x")
        widget = Select(self.body, items, value, lambda _v: self.update_notes(), width=44)
        widget.pack(fill="x", pady=(0, 8))
        return widget

    def _check(self):
        s = self.screen
        return check_substitution(
            self.repo, s.version, s.state.date, s.offset, self.row,
            self.teacher.value(), self.subject.value(), self.room.value(),
        )

    def update_notes(self):
        for child in self.notes.winfo_children():
            child.destroy()
        if self.cancelled.get():
            note(self.notes, "В этот день урок будет отменён, кабинет и учитель освободятся.", "neutral").pack(fill="x", pady=(0, 4))
            return
        result = self._check()
        if result.room_busy:
            note(self.notes, result.room_busy, "conflict").pack(fill="x", pady=(0, 4))
        for text in dict.fromkeys(result.warnings):
            note(self.notes, text, "warning").pack(fill="x", pady=(0, 4))
        if not result.room_busy and not result.warnings:
            note(self.notes, "Накладок нет", "ok").pack(fill="x", pady=(0, 4))

    def save(self):
        row = self.row
        cancelled = self.cancelled.get()
        if not cancelled and self._check().room_busy:
            self.update_notes()
            return
        teacher, subject, room = self.teacher.value(), self.subject.value(), self.room.value()
        # в таблице только отличия: если потом поправят расписание, остальное подтянется само
        new_teacher = teacher if teacher != row["base_teacher_id"] else None
        new_subject = subject if subject != row["base_subject_id"] else None
        new_room = room if room != row["base_room_id"] else None
        text = self.note.get().strip()
        lesson, date = row["lesson_id"], self.screen.state.date.isoformat()
        screen, repo = self.screen, self.repo
        self.destroy()
        if not (new_teacher or new_subject or new_room or cancelled or text):
            if row["substitution_id"]:
                screen.app.mutate("Замена убрана", lambda: repo.delete_substitution(lesson, date))
            return
        screen.app.mutate(
            "Замена сохранена",
            lambda: repo.save_substitution(lesson, date, new_teacher, new_subject, new_room, cancelled, text),
        )

    def remove(self):
        lesson, date = self.row["lesson_id"], self.screen.state.date.isoformat()
        app, repo = self.screen.app, self.repo
        self.destroy()
        app.mutate("Замена убрана", lambda: repo.delete_substitution(lesson, date))
