import tkinter as tk

from timetra.services.checks import CONFLICT, find_problems
from timetra.ui.theme import colors as c
from timetra.ui.widgets import Btn, Scroll, badge, label


class HelpScreen(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=c["bg"])
        self.app = app
        repo = app.repo
        label(self, "С чего начать", 15, True, anchor="w").pack(fill="x")
        label(self, "Пять шагов от пустой программы до готового расписания.", color="muted", anchor="w").pack(fill="x", pady=(0, 10))
        workload = repo.workload(app.version_id)
        refs_ready = all((repo.classes(), repo.teachers(), repo.subjects(), repo.rooms()))
        all_placed = bool(workload) and all(w["placed"] >= w["lessons_per_fortnight"] for w in workload)
        no_conflicts = not any(p.severity == CONFLICT for p in find_problems(repo, app.version_id))
        steps = [
            ("Заполните справочники", "Добавьте учителей, классы, предметы и кабинеты. Можно загрузить их из файла Excel.", "refs", "Открыть справочники", refs_ready),
            ("Заполните нагрузку", "Укажите, кто какой предмет ведёт и сколько уроков в каждом классе.", "load", "Открыть нагрузку", bool(workload)),
            ("Расставьте уроки", "Перетащите уроки в сетку или нажмите «Расставить автоматически».", "schedule", "Открыть расписание", all_placed),
            ("Исправьте ошибки", "Программа покажет накладки и подскажет, что сделать.", "check", "Открыть проверку", all_placed and no_conflicts),
            ("Сохраните результат", "Сохраните расписание в файл Excel, чтобы распечатать или отправить.", "exchange", "Сохранить в файл", False),
        ]
        scroll = Scroll(self)
        scroll.pack(fill="both", expand=True)
        for i, (title, text, screen, button, done) in enumerate(steps, start=1):
            card = tk.Frame(scroll.inner, bg=c["surface"], highlightthickness=1, highlightbackground=c["border"], padx=12, pady=9)
            card.pack(fill="x", pady=(0, 8), padx=(0, 4))
            if done:
                badge(card, "Готово", "ok", "check").pack(side="left", padx=(0, 12))
            else:
                badge(card, f"Шаг {i}").pack(side="left", padx=(0, 12))
            Btn(card, button, None, lambda s=screen: self.app.go(s)).pack(side="right", padx=(10, 0))
            box = tk.Frame(card, bg=c["surface"])
            box.pack(side="left", fill="x", expand=True)
            label(box, title, 10, True, bg="surface", anchor="w").pack(fill="x")
            label(box, text, 9, color="muted", bg="surface", anchor="w", wraplength=620, justify="left").pack(fill="x")
