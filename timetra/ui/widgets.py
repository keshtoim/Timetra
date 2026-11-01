import tkinter as tk
from tkinter import ttk

from timetra.ui.theme import colors as c
from timetra.ui.theme import font, icon_font

# коды значков шрифта Segoe MDL2 Assets
ICONS = {
    "calendar": "", "warning": "", "book": "", "list": "", "swap": "",
    "settings": "", "help": "", "add": "", "edit": "", "delete": "",
    "undo": "", "check": "", "close": "", "copy": "", "star": "",
    "upload": "", "download": "", "wand": "", "save": "",
}

tips_enabled = True
_TIP_DELAY_MS = 500


def set_tips_enabled(value: bool) -> None:
    global tips_enabled
    tips_enabled = value


class Tooltip:
    def __init__(self, widget: tk.Misc, text: str) -> None:
        self.widget = widget
        self.text = text
        self.window = None
        self.job = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        widget.bind("<Destroy>", self._hide, add="+")

    def _schedule(self, _event=None):
        if tips_enabled and self.text and not self.job:
            self.job = self.widget.after(_TIP_DELAY_MS, self._show)

    def _show(self):
        self.job = None
        if not self.widget.winfo_exists():
            return
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.attributes("-topmost", True)
        tk.Label(
            self.window, text=self.text, bg=c["tip_bg"], fg=c["tip_fg"], font=font(9),
            padx=8, pady=4, wraplength=300, justify="left",
        ).pack()
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.window.wm_geometry(f"+{x}+{y}")

    def _hide(self, _event=None):
        if self.job:
            self.widget.after_cancel(self.job)
            self.job = None
        if self.window:
            self.window.destroy()
            self.window = None


def tip(widget: tk.Misc, text: str | None) -> None:
    if text:
        Tooltip(widget, text)


class Btn(tk.Frame):
    """Кнопка со значком и подписью: у tk.Button нет разных шрифтов для значка и текста."""

    def __init__(self, parent, text, icon=None, command=None, kind="normal", tooltip=None, disabled=False):
        palette = {
            "normal": (c["surface"], c["text"], c["border"]),
            "primary": (c["accent"], c["on_accent"], c["accent"]),
            "danger": (c["surface"], c["conflict"], c["conflict"]),
        }[kind]
        self.bg_color, fg, border = palette
        self.command = None if disabled else command
        if disabled:
            fg = c["muted"]
        super().__init__(
            parent, bg=self.bg_color, highlightthickness=1, highlightbackground=border, highlightcolor=c["accent"],
            takefocus=not disabled, cursor="arrow" if disabled else "hand2",
        )
        self.parts = [self]
        if icon:
            label = tk.Label(self, text=ICONS[icon], font=icon_font(), bg=self.bg_color, fg=fg)
            label.pack(side="left", padx=(9, 0), pady=4)
            self.parts.append(label)
        label = tk.Label(self, text=text, font=font(10, kind == "primary"), bg=self.bg_color, fg=fg)
        label.pack(side="left", padx=(5 if icon else 10, 10), pady=4)
        self.parts.append(label)
        self.hover_color = self.bg_color if kind == "primary" or disabled else c["hover"]
        for part in self.parts:
            part.bind("<ButtonRelease-1>", self._click)
            part.bind("<Enter>", lambda _e: self._paint(self.hover_color))
            part.bind("<Leave>", lambda _e: self._paint(self.bg_color))
        self.bind("<Return>", self._click)
        self.bind("<space>", self._click)
        self.bind("<FocusIn>", lambda _e: self.configure(highlightbackground=c["accent"]))
        self.bind("<FocusOut>", lambda _e: self.configure(highlightbackground=border))
        tip(self, tooltip)

    def _paint(self, color):
        for part in self.parts:
            part.configure(bg=color)

    def _click(self, _event=None):
        if self.command:
            self.command()


class Seg(tk.Frame):
    """Группа кнопок, из которых выбрана одна."""

    def __init__(self, parent, options, value, command):
        super().__init__(parent, bg=c["border"], highlightthickness=0)
        for i, option in enumerate(options):
            val, text, *rest = option
            selected = val == value
            label = tk.Label(
                self, text=text, font=font(10, selected), padx=10, pady=4, cursor="hand2", takefocus=True,
                bg=c["accent"] if selected else c["surface"], fg=c["on_accent"] if selected else c["text"],
            )
            label.grid(row=0, column=i, padx=(1, 1 if i == len(options) - 1 else 0), pady=1)
            handler = lambda _e, v=val: command(v)
            label.bind("<ButtonRelease-1>", handler)
            label.bind("<Return>", handler)
            label.bind("<space>", handler)
            if not selected:
                label.bind("<Enter>", lambda e: e.widget.configure(bg=c["hover"]))
                label.bind("<Leave>", lambda e: e.widget.configure(bg=c["surface"]))
            tip(label, rest[0] if rest else None)


class Select(ttk.Combobox):
    """Выпадающий список, работающий со значениями, а не с подписями."""

    def __init__(self, parent, items, value=None, command=None, width=None, tooltip=None):
        self.items = list(items)
        labels = [label for _v, label in self.items]
        width = width or min(40, max([len(label) for label in labels] + [8]) + 2)
        super().__init__(parent, values=labels, state="readonly", width=width, font=font())
        self.set_value(value)
        if command:
            self.bind("<<ComboboxSelected>>", lambda _e: command(self.value()))
        # колесо мыши иначе незаметно меняет значение при прокрутке страницы
        self.bind("<MouseWheel>", lambda _e: "break")
        tip(self, tooltip)

    def set_value(self, value):
        for i, (val, _label) in enumerate(self.items):
            if val == value:
                self.current(i)
                return
        if self.items:
            self.current(0)

    def value(self):
        index = self.current()
        return self.items[index][0] if index >= 0 else None


def label(parent, text, size=10, bold=False, color="text", bg="bg", **kw):
    return tk.Label(parent, text=text, font=font(size, bold), fg=c[color], bg=c[bg], **kw)


def icon_label(parent, icon, color="text", bg="bg", size=11):
    return tk.Label(parent, text=ICONS[icon], font=icon_font(size), fg=c[color], bg=c[bg])


def badge(parent, text, kind="neutral", icon=None):
    fg, bg = {
        "conflict": (c["conflict"], c["conflict_soft"]), "warning": (c["warn"], c["warn_soft"]),
        "ok": (c["ok"], c["ok_soft"]), "neutral": (c["muted"], c["hover"]),
    }[kind]
    frame = tk.Frame(parent, bg=bg)
    if icon:
        tk.Label(frame, text=ICONS[icon], font=icon_font(9), fg=fg, bg=bg).pack(side="left", padx=(6, 0))
    tk.Label(frame, text=text, font=font(9, True), fg=fg, bg=bg, padx=6, pady=1).pack(side="left")
    return frame


def note(parent, text, kind="neutral", bg_parent=None):
    fg, bg = {
        "conflict": (c["conflict"], c["conflict_soft"]), "warning": (c["warn"], c["warn_soft"]),
        "ok": (c["ok"], c["ok_soft"]), "neutral": (c["muted"], c["hover"]),
    }[kind]
    frame = tk.Frame(parent, bg=bg)
    glyph = {"conflict": "warning", "warning": "warning", "ok": "check", "neutral": "help"}[kind]
    tk.Label(frame, text=ICONS[glyph], font=icon_font(10), fg=fg, bg=bg).pack(side="left", padx=(8, 0), pady=5, anchor="n")
    tk.Label(
        frame, text=text, font=font(10), fg=fg, bg=bg, wraplength=420, justify="left", padx=6, pady=5,
    ).pack(side="left", fill="x")
    return frame


class Scroll(tk.Frame):
    """Прокручиваемая область. Колесо мыши обрабатывает общий обработчик в App."""

    def __init__(self, parent, horizontal=False, bg="bg", **kw):
        super().__init__(parent, bg=c[bg], **kw)
        self.canvas = tk.Canvas(self, bg=c[bg], highlightthickness=0)
        self.inner = tk.Frame(self.canvas, bg=c[bg])
        self.window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vbar.grid(row=0, column=1, sticky="ns")
        self.horizontal = horizontal
        if horizontal:
            self.hbar = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
            self.canvas.configure(xscrollcommand=self.hbar.set)
            self.hbar.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)

    def _on_inner(self, _event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, event):
        # без горизонтальной прокрутки содержимое занимает всю ширину
        width = max(event.width, self.inner.winfo_reqwidth()) if self.horizontal else event.width
        self.canvas.itemconfigure(self.window, width=width)

    def wheel(self, delta, shift=False):
        step = -1 if delta > 0 else 1
        if shift and self.horizontal:
            self.canvas.xview_scroll(step * 3, "units")
        elif self.inner.winfo_reqheight() > self.canvas.winfo_height():
            self.canvas.yview_scroll(step * 3, "units")

    def position(self):
        return self.canvas.xview()[0], self.canvas.yview()[0]

    def restore_position(self, pos):
        self.canvas.update_idletasks()
        self.canvas.xview_moveto(pos[0])
        self.canvas.yview_moveto(pos[1])


class DataTable(tk.Frame):
    """Таблица с кнопками прямо в строке: людям проще, чем выделять строку и искать кнопку."""

    def __init__(self, parent, columns, rows, actions=None):
        super().__init__(parent, bg=c["surface"], highlightthickness=1, highlightbackground=c["border"])
        for col, title in enumerate(columns):
            text, hint = title if isinstance(title, tuple) else (title, None)
            head = label(self, text, 9, True, "muted", "surface", padx=10, pady=6, anchor="w")
            head.grid(row=0, column=col, sticky="ew")
            tip(head, hint)
            self.columnconfigure(col, weight=1)
        row_index = 1
        for row in rows:
            tk.Frame(self, bg=c["border"], height=1).grid(
                row=row_index, column=0, columnspan=len(columns) + 1, sticky="ew"
            )
            row_index += 1
            for col, value in enumerate(row["cells"]):
                if callable(value):
                    holder = tk.Frame(self, bg=c["surface"])
                    value(holder).pack(anchor="w")
                    holder.grid(row=row_index, column=col, sticky="w", padx=10, pady=4)
                else:
                    text = "—" if value in (None, "") else str(value)
                    label(self, text, bg="surface", anchor="w", padx=10, pady=6, wraplength=320, justify="left").grid(
                        row=row_index, column=col, sticky="ew"
                    )
            if actions:
                box = tk.Frame(self, bg=c["surface"])
                for text, icon, command in actions:
                    Btn(box, text, icon, lambda cmd=command, key=row["id"]: cmd(key)).pack(side="left", padx=(0, 6))
                box.grid(row=row_index, column=len(columns), sticky="e", padx=(4, 6), pady=3)
            row_index += 1
