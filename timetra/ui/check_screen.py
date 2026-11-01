import tkinter as tk

from timetra.services.checks import CONFLICT, find_problems
from timetra.ui.theme import colors as c
from timetra.ui.widgets import Btn, Scroll, badge, label, note

FLASH_MS = 2600


class CheckScreen(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=c["bg"])
        self.app = app
        self.repo = app.repo
        version = next(v for v in self.repo.versions() if v["id"] == app.version_id)
        label(self, "Проверка", 15, True, anchor="w").pack(fill="x")
        label(
            self, f"Вариант «{version['name']}». Программа сама ищет ошибки после каждого изменения.",
            color="muted", anchor="w",
        ).pack(fill="x", pady=(0, 10))
        problems = find_problems(self.repo, app.version_id)
        if not problems:
            note(self, "Ошибок нет. Расписание можно сохранять в файл.", "ok").pack(fill="x")
            return
        self.days = {d["id"]: d["name"] for d in self.repo.weekdays()}
        self.slots = {s["id"]: s["number"] for s in self.repo.slots()}
        self.weeks = {w["id"]: w["name"].lower() for w in self.repo.week_types()}
        scroll = Scroll(self)
        scroll.pack(fill="both", expand=True)
        box = tk.Frame(scroll.inner, bg=c["surface"], highlightthickness=1, highlightbackground=c["border"])
        box.pack(fill="x")
        for i, problem in enumerate(problems):
            if i:
                tk.Frame(box, bg=c["border"], height=1).pack(fill="x")
            self._row(box, problem)

    def _row(self, parent, problem):
        row = tk.Frame(parent, bg=c["surface"], padx=12, pady=9)
        row.pack(fill="x")
        conflict = problem.severity == CONFLICT
        badge(row, "Накладка" if conflict else "Предупреждение", "conflict" if conflict else "warning", "warning").pack(side="left", anchor="n", padx=(0, 10))
        Btn(
            row, "Показать в расписании", None, lambda: self.show(problem),
            tooltip="Перейти к этому уроку в расписании",
        ).pack(side="right", anchor="n", padx=(10, 0))
        text = tk.Frame(row, bg=c["surface"])
        text.pack(side="left", fill="x", expand=True)
        label(text, problem.title, 10, True, bg="surface", anchor="w", wraplength=640, justify="left").pack(fill="x")
        weeks = "обе недели" if len(problem.weeks) > 1 else f"{self.weeks[next(iter(problem.weeks))]} неделя"
        where = f"{self.days[problem.day]}, {self.slots[problem.slot]} урок, {weeks}. {problem.text}"
        label(text, where, 9, color="muted", bg="surface", anchor="w", wraplength=640, justify="left").pack(fill="x")
        label(text, problem.fix, 9, color="muted", bg="surface", anchor="w", wraplength=640, justify="left").pack(fill="x")

    def show(self, problem):
        state = self.app.schedule_state
        state.view = "classes"
        state.day = problem.day
        state.week = min(problem.weeks)
        state.pick = None
        state.flash = set(problem.lesson_ids)
        shift = next(s["shift_id"] for s in self.repo.slots() if s["id"] == problem.slot)
        state.shift = shift
        self.app.go("schedule")
        self.app.after(FLASH_MS, self._clear_flash)

    def _clear_flash(self):
        self.app.schedule_state.flash = set()
        if self.app.screen == "schedule":
            self.app.refresh()
