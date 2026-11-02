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
    check_extra,
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
WEEK_HINT = "Если неделя определилась неверно, нажмите правильную: программа запомнит"


@dataclass
class SubstitutionsState:
    date: datetime.date = field(default_factory=datetime.date.today)
    teacher_id: int | None = None
    class_id: int | None = None
    only_changed: bool = False


def slot_items(repo, shift_id):
    return [(s["id"], f"{s['number']} урок" + (f" ({s['starts_at']})" if s["starts_at"] else "")) for s in repo.slots(shift_id)]


class DateBar(tk.Frame):
    """Выбор даты и чётности недели: дата общая для экрана замен и вкладки «На дату»."""

    def __init__(self, parent, app):
        super().__init__(parent, bg=parent.cget("bg"))
        self.app = app
        date = app.substitutions_state.date
        label(self, "Дата", 9, color="muted", bg="surface").pack(side="left", padx=(0, 6))
        Btn(self, "Назад", "collapse", lambda: self.set_date(self.current() - ONE_DAY), tooltip="Предыдущий день").pack(side="left")
        self.entry = tk.Entry(
            self, font=font(11, True), bg=c["surface"], fg=c["text"], insertbackground=c["text"], relief="flat", justify="center",
            highlightthickness=1, highlightbackground=c["border"], highlightcolor=c["accent"], width=11,
        )
        self.entry.insert(0, date.strftime(DATE_FORMAT))
        self.entry.pack(side="left", padx=6, ipady=3)
        self.entry.bind("<Return>", lambda _e: self.apply_entered())
        self.entry.bind("<FocusOut>", lambda _e: self.apply_entered())
        Btn(self, "Вперёд", "expand", lambda: self.set_date(self.current() + ONE_DAY), tooltip="Следующий день").pack(side="left")
        Btn(self, "Сегодня", None, lambda: self.set_date(datetime.date.today())).pack(side="left", padx=(6, 14))
        days = {d["id"]: d["name"] for d in app.repo.weekdays()}
        label(self, days.get(date.isoweekday(), "Воскресенье"), 11, True, bg="surface").pack(side="left", padx=(0, 14))
        label(self, "Неделя", 9, color="muted", bg="surface").pack(side="left", padx=(0, 6))
        week = week_for_date(date, app.settings.week_offset)
        Seg(self, [(ODD, "Нечётная", WEEK_HINT), (EVEN, "Чётная", WEEK_HINT)], week, self.set_week).pack(side="left")

    def current(self):
        return self.app.substitutions_state.date

    def set_date(self, date):
        self.app.substitutions_state.date = date
        self.app.refresh()

    def apply_entered(self):
        if not self.entry.winfo_exists():
            return
        date = parse_date(self.entry.get())
        if date is None:
            self.entry.delete(0, "end")
            self.entry.insert(0, self.current().strftime(DATE_FORMAT))
            self.app.toast("Укажите дату так: 02.11.2026")
        elif date != self.current():
            self.set_date(date)

    def set_week(self, week):
        settings = self.app.settings
        if week == week_for_date(self.current(), settings.week_offset):
            return
        settings.week_offset = 1 - settings.week_offset
        self.app.settings_changed(rebuild=False)
        self.app.refresh()
        self.app.toast("Запомнил: чётность недель переключена для всех дат")


def open_day_dialog(app, row):
    (ExtraLessonDialog(app, row) if row["extra_id"] else SubstitutionDialog(app, row))


class SubstitutionsScreen(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=c["bg"])
        self.app = app
        self.repo = app.repo
        self.state = app.substitutions_state
        # замены относятся к настоящему расписанию, а не к черновику, открытому на другом экране
        self.version = self.repo.active_version_id()
        self.rows = day_lessons(self.repo, self.version, self.state.date, app.settings.week_offset)
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
            row, "Добавить урок", "add", lambda: ExtraLessonDialog(self.app), "primary",
            "Дополнительный урок только на этот день, которого нет в расписании",
            disabled=self.state.date.isoweekday() == SUNDAY,
        ).pack(side="right")
        Btn(
            row, "Сохранить замены в файл", "save", self.save_file,
            tooltip="Файл Excel со всеми заменами этого дня, например для печати",
            disabled=not any(r["substitution_id"] for r in self.rows),
        ).pack(side="right", padx=8)
        Btn(row, "Отменить", "undo", self.app.undo, disabled=not self.app.undo_stack, tooltip="Вернуть как было до последнего изменения").pack(side="right")

    def _build_tools(self):
        s = self.state
        box = tk.Frame(self, bg=c["surface"], highlightthickness=1, highlightbackground=c["border"], padx=10, pady=8)
        box.pack(fill="x", pady=(0, 8))
        self.date_bar = DateBar(box, self.app)
        self.date_bar.pack(fill="x", pady=2)
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
        self.visible = rows
        table_rows = [self._table_row(i, r) for i, r in enumerate(rows)]
        columns = ["Класс", "Урок", "Предмет", "Учитель", "Кабинет", "Замена"]
        DataTable(scroll.inner, columns, table_rows, [("Заменить", "edit", self.edit)]).pack(fill="x")

    def _table_row(self, index, row):
        group = f" (гр. {row['subgroup']})" if row["subgroup"] else ""
        change = describe_change(row)
        if row["note"]:
            change = f"{change} ({row['note']})" if change else row["note"]
        kind = "conflict" if row["is_cancelled"] else "warning"
        cell = (lambda parent, t=change, k=kind: badge(parent, t, k)) if change else ""
        return {
            "id": index,
            "cells": [row["class_name"], row["lesson_number"], row["base_subject"] + group, row["base_teacher"], row["base_room"], cell],
        }

    def edit(self, index):
        open_day_dialog(self.app, self.visible[index])

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


class _DayDialog(Dialog):
    def __init__(self, app, title):
        self.repo = app.repo
        self.date = app.substitutions_state.date
        self.offset = app.settings.week_offset
        self.version = app.repo.active_version_id()
        super().__init__(app, title)

    def _select(self, title, items, value, width=44):
        label(self.body, title, 9, color="muted", bg="surface", anchor="w").pack(fill="x")
        widget = Select(self.body, items, value, lambda _v: self.update_notes(), width=width)
        widget.pack(fill="x", pady=(0, 8))
        return widget

    def _note_field(self, value):
        label(self.body, "Примечание", 9, color="muted", bg="surface", anchor="w").pack(fill="x")
        entry = tk.Entry(
            self.body, font=font(), bg=c["surface"], fg=c["text"], insertbackground=c["text"], relief="flat",
            highlightthickness=1, highlightbackground=c["border"], highlightcolor=c["accent"],
        )
        entry.insert(0, value or "")
        entry.pack(fill="x", ipady=3, pady=(0, 8))
        self.notes = tk.Frame(self.body, bg=c["surface"])
        self.notes.pack(fill="x")
        return entry

    def _show_result(self, result):
        for child in self.notes.winfo_children():
            child.destroy()
        if result.room_busy:
            note(self.notes, result.room_busy, "conflict").pack(fill="x", pady=(0, 4))
        for text in dict.fromkeys(result.warnings):
            note(self.notes, text, "warning").pack(fill="x", pady=(0, 4))
        if not result.room_busy and not result.warnings:
            note(self.notes, "Накладок нет", "ok").pack(fill="x", pady=(0, 4))


class SubstitutionDialog(_DayDialog):
    def __init__(self, app, row):
        self.row = row
        super().__init__(app, "Замена урока")
        group = f" (гр. {row['subgroup']})" if row["subgroup"] else ""
        text = f"{self.date.strftime(DATE_FORMAT)}, {row['class_name']}. По расписанию: {row['lesson_number']} урок, {row['base_subject']}{group}, {row['base_teacher']}"
        label(self.body, text, 9, color="muted", bg="surface", anchor="w", wraplength=440, justify="left").pack(fill="x", pady=(0, 8))
        free = free_teacher_ids(self.repo, self.version, self.date, self.offset, row)
        teachers = sorted(self.repo.teachers(), key=lambda t: (t["id"] not in free, t["short"]))
        self.teacher = self._select("Кто ведёт", [(t["id"], f"{t['short']}{'' if t['id'] in free else ' (занят)'}") for t in teachers], row["eff_teacher_id"])
        self.subject = self._select("Предмет", [(s["id"], s["name"]) for s in self.repo.subjects()], row["eff_subject_id"])
        self.slot = self._select("Какой урок (перенос на этот день)", slot_items(self.repo, row["shift_id"]), row["eff_slot_id"])
        self.room = self._select(
            "Кабинет", [(None, "Без кабинета"), *[(r["id"], f"{r['number']} ({r['type_name']})") for r in self.repo.rooms()]], row["eff_room_id"],
        )
        self.cancelled = tk.BooleanVar(value=bool(row["is_cancelled"]))
        tk.Checkbutton(
            self.body, text="Урока не будет", variable=self.cancelled, command=self.update_notes, font=font(), bg=c["surface"],
            fg=c["text"], selectcolor=c["surface"], activebackground=c["surface"], activeforeground=c["text"], anchor="w",
        ).pack(fill="x", pady=(0, 6))
        self.note = self._note_field(row["note"])
        buttons = self.footer()
        Btn(buttons, "Сохранить", "check", self.save, "primary").pack(side="right")
        Btn(buttons, "Отмена", None, self.destroy).pack(side="right", padx=(0, 8))
        if row["substitution_id"]:
            Btn(buttons, "Убрать замену", "delete", self.remove, "danger").pack(side="left")
        self.update_notes()
        self.show()

    def _check(self):
        return check_substitution(
            self.repo, self.version, self.date, self.offset, self.row,
            self.teacher.value(), self.subject.value(), self.room.value(), self.slot.value(),
        )

    def update_notes(self):
        if self.cancelled.get():
            for child in self.notes.winfo_children():
                child.destroy()
            note(self.notes, "В этот день урок будет отменён, кабинет и учитель освободятся.", "neutral").pack(fill="x", pady=(0, 4))
            return
        self._show_result(self._check())

    def save(self):
        row = self.row
        cancelled = self.cancelled.get()
        if not cancelled and self._check().room_busy:
            self.update_notes()
            return
        teacher, subject, room, slot = self.teacher.value(), self.subject.value(), self.room.value(), self.slot.value()
        # в таблице только отличия: если потом поправят расписание, остальное подтянется само
        new_teacher = teacher if teacher != row["base_teacher_id"] else None
        new_subject = subject if subject != row["base_subject_id"] else None
        new_room = room if room != row["base_room_id"] else None
        new_slot = slot if slot != row["lesson_slot_id"] else None
        text = self.note.get().strip()
        lesson, date, app, repo = row["lesson_id"], self.date.isoformat(), self.app, self.repo
        self.destroy()
        if not (new_teacher or new_subject or new_room or new_slot or cancelled or text):
            if row["substitution_id"]:
                app.mutate("Замена убрана", lambda: repo.delete_substitution(lesson, date))
            return
        app.mutate(
            "Замена сохранена",
            lambda: repo.save_substitution(lesson, date, new_teacher, new_subject, new_room, cancelled, text, new_slot),
        )

    def remove(self):
        lesson, date, app, repo = self.row["lesson_id"], self.date.isoformat(), self.app, self.repo
        self.destroy()
        app.mutate("Замена убрана", lambda: repo.delete_substitution(lesson, date))


class ExtraLessonDialog(_DayDialog):
    def __init__(self, app, row=None, class_id=None, slot_id=None):
        self.row = row
        classes, subjects, teachers = app.repo.classes(), app.repo.subjects(), app.repo.teachers()
        missing = [n for n, items in (("классы", classes), ("предметы", subjects), ("учителей", teachers)) if not items]
        if missing:
            info_dialog(app, "Сначала заполните справочники", f"В разделе «Справочники» добавьте: {', '.join(missing)}.")
            return
        super().__init__(app, "Изменить дополнительный урок" if row else "Дополнительный урок")
        label(self.body, f"Только на {self.date.strftime(DATE_FORMAT)}, в расписание не попадёт.", 9, color="muted", bg="surface", anchor="w").pack(fill="x", pady=(0, 8))
        self.classes = {x["id"]: x for x in classes}
        current_class = row["class_id"] if row else class_id or classes[0]["id"]
        label(self.body, "Класс", 9, color="muted", bg="surface", anchor="w").pack(fill="x")
        self.cls = Select(self.body, [(x["id"], x["name"]) for x in classes], current_class, self._class_changed, width=44)
        self.cls.pack(fill="x", pady=(0, 8))
        self.group = self._select("Кто учится", [(0, "Весь класс"), (1, "Группа 1"), (2, "Группа 2"), (3, "Группа 3")], row["subgroup"] if row else 0)
        self.subject = self._select("Предмет", [(s["id"], s["name"]) for s in subjects], row and row["eff_subject_id"])
        self.teacher = self._select("Кто ведёт", [(t["id"], t["short"]) for t in teachers], row and row["eff_teacher_id"])
        self.slot = self._select("Какой урок", slot_items(self.repo, self.classes[current_class]["shift_id"]), row["eff_slot_id"] if row else slot_id)
        self.room = self._select(
            "Кабинет", [(None, "Выбрать позже"), *[(r["id"], f"{r['number']} ({r['type_name']})") for r in self.repo.rooms()]],
            row["eff_room_id"] if row else None,
        )
        self.note = self._note_field(row["note"] if row else "")
        buttons = self.footer()
        Btn(buttons, "Сохранить", "check", self.save, "primary").pack(side="right")
        Btn(buttons, "Отмена", None, self.destroy).pack(side="right", padx=(0, 8))
        if row:
            Btn(buttons, "Удалить урок", "delete", self.remove, "danger").pack(side="left")
        self.update_notes()
        self.show()

    def _class_changed(self, class_id):
        # в другой смене другие номера уроков
        items = slot_items(self.repo, self.classes[class_id]["shift_id"])
        self.slot.items = items
        self.slot.configure(values=[text for _v, text in items])
        self.slot.set_value(None)
        self.update_notes()

    def _check(self):
        return check_extra(
            self.repo, self.version, self.date, self.offset, self.cls.value(), self.group.value(), self.slot.value(),
            self.teacher.value(), self.subject.value(), self.room.value(), self.row,
        )

    def update_notes(self):
        self._show_result(self._check())

    def save(self):
        if self.slot.value() is None:
            return
        if self._check().room_busy:
            self.update_notes()
            return
        extra_id = self.row["extra_id"] if self.row else None
        week = week_for_date(self.date, self.offset)
        values = (
            extra_id, self.version, self.date.isoformat(), week, self.slot.value(), self.cls.value(), self.group.value(),
            self.subject.value(), self.teacher.value(), self.room.value(), self.note.get().strip(),
        )
        app, repo = self.app, self.repo
        self.destroy()
        app.mutate("Урок сохранён" if extra_id else "Дополнительный урок добавлен", lambda: repo.save_extra(*values))

    def remove(self):
        extra_id, app, repo = self.row["extra_id"], self.app, self.repo
        self.destroy()
        app.mutate("Дополнительный урок удалён", lambda: repo.delete_extra(extra_id))
