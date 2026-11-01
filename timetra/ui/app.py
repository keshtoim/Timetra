import sqlite3
import tkinter as tk
from pathlib import Path

from timetra.db.repo import Repo
from timetra.services.checks import CONFLICT, find_problems
from timetra.settings import load_settings, save_settings
from timetra.ui import theme
from timetra.ui.dialogs import info_dialog
from timetra.ui.load_screen import LoadScreen
from timetra.ui.refs_screen import RefsScreen
from timetra.ui.schedule_grid import ScheduleGrid
from timetra.ui.schedule_screen import ScheduleScreen, ScheduleState
from timetra.ui.settings_screen import SettingsScreen
from timetra.ui.theme import colors as c
from timetra.ui.theme import font
from timetra.ui.widgets import ICONS, Scroll, badge, set_tips_enabled, tip

UNDO_LIMIT = 30
TOAST_MS = 7000

SCREENS = [
    ("schedule", "calendar", "Расписание", "Главный экран: сетка уроков по дням и классам", ScheduleScreen),
    ("load", "book", "Нагрузка", "Кто какой предмет ведёт и сколько уроков нужно поставить", LoadScreen),
    ("refs", "list", "Справочники", "Учителя, классы, предметы, кабинеты и звонки", RefsScreen),
    ("settings", "settings", "Настройки", "Тема оформления, размер текста, подсказки", SettingsScreen),
]


def friendly_error(error: sqlite3.IntegrityError) -> str:
    text = str(error)
    if "Кабинет занят" in text:
        return "Этот кабинет занят на этом уроке. Выберите другой кабинет или другое время."
    if "UNIQUE" in text:
        return "Такая запись уже есть."
    if "FOREIGN KEY" in text:
        return "Эта запись используется в других данных, поэтому её нельзя изменить или удалить."
    return "Проверьте введённые значения: некоторые из них не подходят."


class App(tk.Tk):
    def __init__(self, conn: sqlite3.Connection, settings_path: Path) -> None:
        super().__init__()
        self.repo = Repo(conn)
        self.repo.ensure_defaults()
        self.settings_path = settings_path
        self.settings = load_settings(settings_path)
        set_tips_enabled(self.settings.tips)
        self.title("Timetra")
        self.geometry("1200x760")
        self.minsize(900, 560)
        self.undo_stack: list[bytes] = []
        self.screen = "schedule"
        self.schedule_state = ScheduleState()
        self.version_id = next(
            (v["id"] for v in self.repo.versions() if v["is_active"]), self.repo.versions()[0]["id"]
        )
        self.toast_job = None
        self.bind_all("<MouseWheel>", self._on_wheel)
        self._build()

    def _build(self):
        for child in self.winfo_children():
            child.destroy()
        theme.apply_theme(self, self.settings.theme, self.settings.big_text)
        self.nav = tk.Frame(self, bg=c["surface"], width=200, highlightthickness=1, highlightbackground=c["border"])
        self.nav.pack(side="left", fill="y")
        self.nav.pack_propagate(False)
        self.content = tk.Frame(self, bg=c["bg"], padx=16, pady=14)
        self.content.pack(side="left", fill="both", expand=True)
        self.toast_box = tk.Frame(self, bg=c["tip_bg"])
        self.refresh()

    def _build_nav(self):
        for child in self.nav.winfo_children():
            child.destroy()
        tk.Label(
            self.nav, text="Timetra", font=font(15, True), fg=c["accent"], bg=c["surface"], anchor="w", padx=14, pady=10,
        ).pack(fill="x")
        problems = find_problems(self.repo, self.version_id)
        for key, icon, text, hint, _factory in SCREENS:
            self._nav_item(key, icon, text, hint, problems if key == "check" else None)

    def _nav_item(self, key, icon, text, hint, problems):
        current = key == self.screen
        bg = c["accent_soft"] if current else c["surface"]
        row = tk.Frame(self.nav, bg=bg, cursor="hand2", takefocus=True)
        row.pack(fill="x", padx=8, pady=1)
        parts = [row]
        parts.append(tk.Label(row, text=ICONS[icon], font=theme.icon_font(12), fg=c["text"], bg=bg))
        parts[-1].pack(side="left", padx=(8, 8), pady=7)
        parts.append(tk.Label(row, text=text, font=font(10, current), fg=c["text"], bg=bg, anchor="w"))
        parts[-1].pack(side="left")
        if problems:
            conflicts = sum(p.severity == CONFLICT for p in problems)
            badge(row, str(conflicts or len(problems)), "conflict" if conflicts else "warning").pack(side="right", padx=6)
        for part in parts:
            part.bind("<ButtonRelease-1>", lambda _e, k=key: self.go(k))
            if not current:
                part.bind("<Enter>", lambda _e, ps=parts: [p.configure(bg=c["hover"]) for p in ps])
                part.bind("<Leave>", lambda _e, ps=parts: [p.configure(bg=c["surface"]) for p in ps])
        row.bind("<Return>", lambda _e, k=key: self.go(k))
        row.bind("<space>", lambda _e, k=key: self.go(k))
        tip(row, hint)

    def go(self, key):
        self.screen = key
        self.refresh()

    def refresh(self):
        self._build_nav()
        for child in self.content.winfo_children():
            child.destroy()
        factory = next(s[4] for s in SCREENS if s[0] == self.screen)
        self.current_screen = factory(self.content, self)
        self.current_screen.pack(fill="both", expand=True)

    def settings_changed(self, rebuild=True):
        save_settings(self.settings_path, self.settings)
        if rebuild:
            self._build()

    def mutate(self, message, action) -> bool:
        """Изменение данных в транзакции со снимком для отмены."""
        snapshot = self.repo.snapshot()
        try:
            with self.repo.conn:
                action()
        except sqlite3.IntegrityError as error:
            info_dialog(self, "Не получилось сохранить", friendly_error(error))
            return False
        self.undo_stack.append(snapshot)
        del self.undo_stack[:-UNDO_LIMIT]
        self.refresh()
        self.toast(message, can_undo=True)
        return True

    def undo(self):
        if not self.undo_stack:
            return
        self.repo.restore(self.undo_stack.pop())
        versions = [v["id"] for v in self.repo.versions()]
        if self.version_id not in versions:
            self.version_id = versions[0]
        self.refresh()
        self.toast("Действие отменено")

    def toast(self, message, can_undo=False):
        box = self.toast_box
        for child in box.winfo_children():
            child.destroy()
        tk.Label(box, text=message, font=font(), bg=c["tip_bg"], fg=c["tip_fg"], padx=12, pady=7).pack(side="left")
        if can_undo:
            link = tk.Label(
                box, text="Отменить", font=(*font(), "underline"), bg=c["tip_bg"], fg=c["tip_fg"], cursor="hand2", padx=8,
            )
            link.pack(side="left")
            link.bind("<ButtonRelease-1>", lambda _e: self.undo())
        box.place(relx=0.5, rely=1.0, y=-16, anchor="s")
        box.lift()
        if self.toast_job:
            self.after_cancel(self.toast_job)
        self.toast_job = self.after(TOAST_MS, self._hide_toast)

    def _hide_toast(self):
        # окно могло быть пересобрано при смене темы, берём актуальный виджет
        self.toast_box.place_forget()

    def _on_wheel(self, event):
        # один обработчик вместо привязок на каждую область: прокручиваем ближайшую под курсором
        try:
            widget = self.winfo_containing(event.x_root, event.y_root)
        except (KeyError, tk.TclError):
            return
        while widget is not None:
            if isinstance(widget, (Scroll, ScheduleGrid)):
                widget.wheel(event.delta, bool(event.state & 0x1))
                return
            widget = widget.master
