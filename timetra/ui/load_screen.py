import tkinter as tk

from timetra.ui.dialogs import FormDialog, confirm_dialog, info_dialog
from timetra.ui.theme import colors as c
from timetra.ui.widgets import Btn, DataTable, Scroll, Select, badge, label


class LoadScreen(tk.Frame):
    class_filter = None  # на уровне класса: фильтр не сбрасывается при обновлении экрана

    def __init__(self, parent, app):
        super().__init__(parent, bg=c["bg"])
        self.app = app
        self.repo = app.repo
        head = tk.Frame(self, bg=c["bg"])
        head.pack(fill="x", pady=(0, 10))
        titles = tk.Frame(head, bg=c["bg"])
        titles.pack(side="left")
        label(titles, "Нагрузка", 15, True, anchor="w").pack(fill="x")
        label(titles, "Кто какой предмет ведёт в каждом классе и сколько уроков нужно поставить за две недели.", color="muted", anchor="w").pack(fill="x")
        Btn(head, "Добавить", "add", lambda: self.edit(None), "primary").pack(side="right")

        row = tk.Frame(self, bg=c["bg"])
        row.pack(fill="x", pady=(0, 10))
        label(row, "Класс", 9, color="muted").pack(side="left", padx=(0, 6))
        items = [(None, "Все классы"), *[(x["id"], x["name"]) for x in self.repo.classes()]]
        Select(row, items, LoadScreen.class_filter, self._filter, width=14).pack(side="left")

        scroll = Scroll(self)
        scroll.pack(fill="both", expand=True)
        rows = [self._row(w) for w in self.repo.workload(app.version_id, LoadScreen.class_filter)]
        columns = [
            "Класс", "Предмет", "Кто учится", "Учитель",
            ("Уроков за 2 недели", "10 уроков за две недели = 5 уроков в неделю"), "Поставлено",
        ]
        if rows:
            DataTable(
                scroll.inner, columns, rows,
                [("Изменить", "edit", self.edit), ("Удалить", "delete", self.delete)],
            ).pack(fill="x")
        else:
            label(scroll.inner, "Пока пусто. Нажмите «Добавить».", color="muted").pack(anchor="w", pady=20)

    def _row(self, w):
        placed, total = w["placed"], w["lessons_per_fortnight"]
        kind = "ok" if placed >= total else "warning" if placed else "neutral"
        return {
            "id": w["id"],
            "cells": [
                w["class_name"], w["subject_name"], f"группа {w['subgroup']}" if w["subgroup"] else "весь класс",
                w["teacher_short"], total, lambda parent, k=kind, t=f"{placed} из {total}": badge(parent, t, k),
            ],
        }

    def _filter(self, value):
        LoadScreen.class_filter = value
        self.app.refresh()

    def edit(self, key):
        classes, subjects, teachers = self.repo.classes(), self.repo.subjects(), self.repo.teachers()
        missing = [n for n, items in (("классы", classes), ("предметы", subjects), ("учителей", teachers)) if not items]
        if missing:
            info_dialog(self.app, "Сначала заполните справочники", f"В разделе «Справочники» добавьте: {', '.join(missing)}.")
            return
        w = self.repo.workload_item(self.app.version_id, key) if key else None
        fields = [
            {"key": "cls", "label": "Класс", "type": "select", "value": w["class_id"] if w else LoadScreen.class_filter, "items": [(x["id"], x["name"]) for x in classes]},
            {"key": "subject", "label": "Предмет", "type": "select", "value": w and w["subject_id"], "items": [(s["id"], s["name"]) for s in subjects]},
            {"key": "sub", "label": "Кто учится", "type": "select", "value": w["subgroup"] if w else 0, "items": [(0, "Весь класс"), (1, "Группа 1"), (2, "Группа 2"), (3, "Группа 3")]},
            {"key": "teacher", "label": "Учитель", "type": "select", "value": w and w["teacher_id"], "items": [(t["id"], t["short"]) for t in teachers]},
            {"key": "lessons", "label": "Уроков за две недели", "type": "number", "required": True, "min": 1, "value": w["lessons_per_fortnight"] if w else 2, "hint": "5 уроков в неделю = 10. Предмет раз в две недели = 1."},
        ]

        def check(v):
            for other in self.repo.workload(self.app.version_id):
                if other["id"] != key and (other["class_id"], other["subject_id"], other["subgroup"]) == (v["cls"], v["subject"], v["sub"]):
                    return "Такая запись для этого класса и предмета уже есть"
            return None

        FormDialog(
            self.app, "Изменить нагрузку" if key else "Добавить нагрузку", fields, check,
            lambda v: self.app.mutate(
                "Сохранено",
                lambda: self.repo.save_workload(key, v["cls"], v["subject"], v["sub"], v["teacher"], v["lessons"]),
            ),
        )

    def delete(self, key):
        w = self.repo.workload_item(self.app.version_id, key)
        count = self.repo.workload_lessons_count(key)
        extra = f" Из расписания будут убраны уроки: {count}." if count else ""
        confirm_dialog(
            self.app, "Удалить нагрузку?", f"{w['class_name']}, {w['subject_name']}.{extra}", "Удалить",
            lambda: self.app.mutate("Нагрузка удалена", lambda: self.repo.delete_workload(key)),
        )
