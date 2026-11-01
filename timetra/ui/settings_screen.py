import sqlite3
import tkinter as tk
from tkinter import filedialog

from timetra.ui.theme import colors as c
from timetra.ui.widgets import Btn, Seg, label, set_tips_enabled


class SettingsScreen(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=c["bg"])
        self.app = app
        label(self, "Настройки", 15, True, anchor="w").pack(fill="x", pady=(0, 10))
        card = tk.Frame(self, bg=c["surface"], highlightthickness=1, highlightbackground=c["border"], padx=14, pady=12)
        card.pack(anchor="w")
        settings = app.settings

        self._title(card, "Оформление")
        Seg(
            card, [("light", "Светлое"), ("dark", "Тёмное"), ("system", "Как в Windows")],
            settings.theme, self._set_theme,
        ).pack(anchor="w", pady=(0, 12))

        self._title(card, "Размер текста")
        Seg(card, [(False, "Обычный"), (True, "Крупный")], settings.big_text, self._set_size).pack(anchor="w", pady=(0, 12))

        self._title(card, "Подсказки")
        self.tips = tk.BooleanVar(value=settings.tips)
        tk.Checkbutton(
            card, text="Показывать всплывающие подсказки", variable=self.tips, command=self._set_tips,
            bg=c["surface"], fg=c["text"], selectcolor=c["surface"], activebackground=c["surface"],
            activeforeground=c["text"],
        ).pack(anchor="w", pady=(0, 12))

        self._title(card, "Резервная копия")
        Btn(
            card, "Сделать копию базы", "save", self._backup,
            tooltip="Сохранить всю базу в один файл на случай сбоя",
        ).pack(anchor="w")
        label(card, "Копия включает все варианты расписания и справочники.", 9, False, "muted", "surface").pack(anchor="w", pady=(4, 0))

    def _title(self, parent, text):
        label(parent, text, 9, False, "muted", "surface", anchor="w").pack(fill="x", pady=(0, 3))

    def _set_theme(self, value):
        self.app.settings.theme = value
        self.app.settings_changed()

    def _set_size(self, value):
        self.app.settings.big_text = value
        self.app.settings_changed()

    def _set_tips(self):
        self.app.settings.tips = self.tips.get()
        set_tips_enabled(self.tips.get())
        self.app.settings_changed(rebuild=False)

    def _backup(self):
        path = filedialog.asksaveasfilename(
            parent=self.app, title="Куда сохранить копию", defaultextension=".db",
            initialfile="timetra_копия.db", filetypes=[("База Timetra", "*.db")],
        )
        if not path:
            return
        target = sqlite3.connect(path)
        try:
            self.app.repo.conn.backup(target)
        finally:
            target.close()
        self.app.toast("Копия базы сохранена")
