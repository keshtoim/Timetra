import re
import tkinter as tk

from timetra.ui.theme import colors as c
from timetra.ui.theme import font
from timetra.ui.widgets import Btn, Select, label, note

TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
NUMBERS_PER_ROW = 6


class Dialog(tk.Toplevel):
    def __init__(self, app, title):
        super().__init__(app)
        self.app = app
        self.title(title)
        self.configure(bg=c["surface"])
        self.transient(app)
        self.resizable(False, False)
        self.body = tk.Frame(self, bg=c["surface"], padx=16, pady=14)
        self.body.pack(fill="both", expand=True)
        label(self.body, title, 12, True, bg="surface", anchor="w").pack(fill="x", pady=(0, 10))
        self.bind("<Escape>", lambda _e: self.destroy())

    def show(self):
        self.update_idletasks()
        x = self.app.winfo_rootx() + (self.app.winfo_width() - self.winfo_reqwidth()) // 2
        y = self.app.winfo_rooty() + (self.app.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.grab_set()
        self.focus_set()

    def footer(self):
        row = tk.Frame(self.body, bg=c["surface"])
        row.pack(fill="x", pady=(12, 0))
        return row


def info_dialog(app, title, text, kind="warning"):
    dialog = Dialog(app, title)
    note(dialog.body, text, kind).pack(fill="x")
    Btn(dialog.footer(), "Понятно", "check", dialog.destroy, "primary").pack(side="right")
    dialog.show()
    return dialog


def confirm_dialog(app, title, text, action_text, action, icon="delete"):
    dialog = Dialog(app, title)
    label(dialog.body, text, bg="surface", wraplength=420, justify="left", anchor="w").pack(fill="x")
    row = dialog.footer()

    def run():
        dialog.destroy()
        action()

    Btn(row, action_text, icon, run, "danger").pack(side="right")
    Btn(row, "Отмена", None, dialog.destroy).pack(side="right", padx=(0, 8))
    dialog.show()
    return dialog


class FormDialog(Dialog):
    """Поля: {key, label, type, value, required, hint, items, min, max}. Тип по умолчанию text.

    check(values) возвращает текст ошибки или None, save(values) выполняется после закрытия окна.
    """

    def __init__(self, app, title, fields, check, save):
        super().__init__(app, title)
        self.fields = fields
        self.check = check
        self.save = save
        self.inputs = {}
        for field in fields:
            self._build_field(field)
        self.error = label(self.body, "", 9, True, "conflict", "surface", wraplength=420, justify="left", anchor="w")
        row = self.footer_row = self.footer()
        Btn(row, "Сохранить", "check", self.submit, "primary").pack(side="right")
        Btn(row, "Отмена", None, self.destroy).pack(side="right", padx=(0, 8))
        self.bind("<Return>", lambda _e: self.submit())
        self.show()
        first = next(iter(self.inputs.values()), None)
        if isinstance(first, tk.Entry):
            first.focus_set()

    def _build_field(self, field):
        kind = field.get("type", "text")
        box = tk.Frame(self.body, bg=c["surface"])
        box.pack(fill="x", pady=(0, 8))
        title = field["label"] + (" *" if field.get("required") else "")
        label(box, title, 9, False, "muted", "surface", anchor="w").pack(fill="x")
        value = field.get("value")
        if kind == "select":
            items = field["items"]
            if "empty" in field:
                items = [(None, field["empty"]), *items]
            widget = Select(box, items, value, width=38)
            widget.pack(fill="x")
        elif kind == "checks":
            frame = tk.Frame(box, bg=c["surface"])
            frame.pack(fill="x")
            widget = {}
            for i, (val, text) in enumerate(field["items"]):
                var = tk.BooleanVar(value=val in (value or ()))
                tk.Checkbutton(
                    frame, text=text, variable=var, font=font(), bg=c["surface"], fg=c["text"],
                    selectcolor=c["surface"], activebackground=c["surface"], activeforeground=c["text"], anchor="w",
                ).grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 10))
                widget[val] = var
        elif kind == "numbers":
            frame = tk.Frame(box, bg=c["surface"])
            frame.pack(anchor="w")
            widget = {}
            for i, (val, text) in enumerate(field["items"]):
                row, col = i // NUMBERS_PER_ROW * 2, i % NUMBERS_PER_ROW
                label(frame, text, 8, False, "muted", "surface").grid(row=row, column=col, sticky="w", padx=(0, 4))
                entry = tk.Entry(
                    frame, font=font(), bg=c["surface"], fg=c["text"], insertbackground=c["text"], relief="flat",
                    highlightthickness=1, highlightbackground=c["border"], highlightcolor=c["accent"], width=5,
                )
                current = (value or {}).get(val)
                entry.insert(0, "" if current is None else str(current))
                entry.grid(row=row + 1, column=col, padx=(0, 4), pady=(0, 4), ipady=2)
                widget[val] = entry
        elif kind == "grid":
            frame = tk.Frame(box, bg=c["surface"])
            frame.pack(anchor="w")
            widget = {}
            for col, (_day, title) in enumerate(field["cols"], start=1):
                label(frame, title, 9, False, "muted", "surface").grid(row=0, column=col, padx=2)
            for row, (slot, title) in enumerate(field["rows"], start=1):
                label(frame, title, 9, False, "muted", "surface").grid(row=row, column=0, padx=(0, 4))
                for col, (day, _t) in enumerate(field["cols"], start=1):
                    var = tk.BooleanVar(value=(day, slot) in (value or ()))
                    tk.Checkbutton(
                        frame, variable=var, bg=c["surface"], selectcolor=c["surface"], fg=c["text"],
                        activebackground=c["surface"], activeforeground=c["text"], padx=0, pady=0,
                    ).grid(row=row, column=col)
                    widget[(day, slot)] = var
        else:
            widget = tk.Entry(
                box, font=font(), bg=c["surface"], fg=c["text"], insertbackground=c["text"], relief="flat",
                highlightthickness=1, highlightbackground=c["border"], highlightcolor=c["accent"], width=40,
            )
            widget.insert(0, "" if value is None else str(value))
            widget.pack(fill="x", ipady=3)
        if field.get("hint"):
            label(box, field["hint"], 8, False, "muted", "surface", anchor="w", wraplength=420, justify="left").pack(fill="x")
        self.inputs[field["key"]] = widget

    def values(self):
        result = {}
        for field in self.fields:
            kind, widget = field.get("type", "text"), self.inputs[field["key"]]
            if kind == "select":
                result[field["key"]] = widget.value()
            elif kind in ("checks", "grid"):
                result[field["key"]] = [k for k, var in widget.items() if var.get()]
            elif kind == "numbers":
                result[field["key"]] = {k: entry.get().strip() for k, entry in widget.items()}
            else:
                result[field["key"]] = widget.get().strip()
        return result

    def _validate(self, values):
        for field in self.fields:
            kind, name, value = field.get("type", "text"), field["label"], values[field["key"]]
            if kind == "numbers":
                parsed = {}
                titles = dict(field["items"])
                for key, text in value.items():
                    if not text:
                        continue
                    if not text.isdigit() or int(text) < field.get("min", 0):
                        return f"В поле «{name}», {titles[key]}: нужно целое число от {field.get('min', 0)}"
                    parsed[key] = int(text)
                values[field["key"]] = parsed
                continue
            if field.get("required") and value in ("", None):
                return f"Заполните поле «{name}»"
            if value == "" and kind in ("number", "time"):
                values[field["key"]] = "" if kind == "time" else None
                continue
            if kind == "number":
                try:
                    number = int(value)
                except ValueError:
                    return f"В поле «{name}» должно быть целое число"
                if ("min" in field and number < field["min"]) or ("max" in field and number > field["max"]):
                    return f"В поле «{name}» число должно быть от {field.get('min', '…')} до {field.get('max', '…')}"
                values[field["key"]] = number
            if kind == "time" and not TIME_RE.match(value):
                return f"В поле «{name}» укажите время, например 08:30"
        return None

    def submit(self):
        values = self.values()
        message = self._validate(values) or (self.check(values) if self.check else None)
        if message:
            self.error.configure(text=message)
            self.error.pack(fill="x", before=self.footer_row)
            return
        self.destroy()
        self.save(values)
