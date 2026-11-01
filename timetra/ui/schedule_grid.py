import bisect
import tkinter as tk
from dataclasses import dataclass
from tkinter import font as tkfont
from tkinter import ttk

from timetra.services.checks import CONFLICT
from timetra.ui import widgets
from timetra.ui.theme import colors as c
from timetra.ui.theme import font

COL_WIDTH = 128
SIDE_WIDTH = 92
HEAD_HEIGHT = 44
SCORE_HEIGHT = 40
CARD_GAP = 3
MIN_ROW_HEIGHT = 66
DRAG_THRESHOLD = 6
TIP_DELAY_MS = 500


@dataclass
class Column:
    title: str
    subtitle: str
    day: int
    class_id: int | None = None
    teacher_id: int | None = None
    room_id: int | None = None


def _fit(text, fnt, width):
    if fnt.measure(text) <= width:
        return text
    while text and fnt.measure(text + "…") > width:
        text = text[:-1]
    return text + "…"


class ScheduleGrid(tk.Frame):
    """Сетка на Canvas: тысяча виджетов-клеток в большой школе перестраивалась бы заметно медленно.

    Шапка и столбец с номерами уроков лежат на отдельных холстах, чтобы не уезжать при прокрутке.
    """

    def __init__(self, parent, screen, columns, slots, lessons, levels, scores=None):
        super().__init__(parent, bg=c["surface"], highlightthickness=1, highlightbackground=c["border"])
        self.screen = screen
        self.columns, self.slots = columns, slots
        self.levels = levels
        self.scores = scores
        self.bold = tkfont.Font(font=font(10, True))
        self.small = tkfont.Font(font=font(9))
        self.line = self.small.metrics("linespace") + 1
        self.by_cell = {}
        for row in lessons:
            for i, col in enumerate(columns):
                if self._matches(row, col):
                    self.by_cell.setdefault((i, row["lesson_slot_id"]), []).append(row)
        self.side_width = int(SIDE_WIDTH * (self.bold.metrics("linespace") / 17))
        self.head = tk.Canvas(self, height=HEAD_HEIGHT, bg=c["surface"], highlightthickness=0)
        self.corner = tk.Canvas(self, width=self.side_width, height=HEAD_HEIGHT, bg=c["surface"], highlightthickness=0)
        self.side = tk.Canvas(self, width=self.side_width, bg=c["surface"], highlightthickness=0)
        self.body = tk.Canvas(self, bg=c["surface"], highlightthickness=0)
        vbar = ttk.Scrollbar(self, orient="vertical", command=self._yview)
        hbar = ttk.Scrollbar(self, orient="horizontal", command=self._xview)
        self.body.configure(yscrollcommand=lambda a, b: self._on_y(vbar, a, b), xscrollcommand=lambda a, b: self._on_x(hbar, a, b))
        self.corner.grid(row=0, column=0, sticky="nsew")
        self.head.grid(row=0, column=1, sticky="ew")
        self.side.grid(row=1, column=0, sticky="ns")
        self.body.grid(row=1, column=1, sticky="nsew")
        vbar.grid(row=0, column=2, rowspan=2, sticky="ns")
        hbar.grid(row=2, column=1, sticky="ew")
        self.rowconfigure(1, weight=1)
        self.columnconfigure(1, weight=1)
        self.col_width = COL_WIDTH
        self.press = None
        self.dragging = False
        self.hover = None
        self.tip_job = None
        self.tip_window = None
        self.body.bind("<Configure>", self._on_resize)
        self.body.bind("<ButtonPress-1>", self._on_press)
        self.body.bind("<B1-Motion>", self._on_drag)
        self.body.bind("<ButtonRelease-1>", self._on_release)
        self.body.bind("<Motion>", self._on_motion)
        self.body.bind("<Leave>", self._on_leave)
        self.bind("<Destroy>", lambda _e: self._hide_tip())
        self._layout()
        self.draw()

    def _matches(self, row, col):
        if row["weekday_id"] != col.day:
            return False
        if col.class_id:
            return row["class_id"] == col.class_id
        if col.teacher_id:
            return row["teacher_id"] == col.teacher_id
        return row["classroom_id"] == col.room_id

    def _xview(self, *args):
        self.body.xview(*args)

    def _yview(self, *args):
        self.body.yview(*args)

    def _on_x(self, bar, first, last):
        bar.set(first, last)
        self.head.xview_moveto(first)
        self.screen.state.grid_pos = (float(first), self.body.yview()[0])

    def _on_y(self, bar, first, last):
        bar.set(first, last)
        self.side.yview_moveto(first)
        self.screen.state.grid_pos = (self.body.xview()[0], float(first))

    def wheel(self, delta, shift=False):
        step = -1 if delta > 0 else 1
        if shift:
            self.body.xview_scroll(step * 3, "units")
        else:
            self.body.yview_scroll(step * 3, "units")

    def _on_resize(self, event):
        # столбцы растягиваются на всю ширину, если их мало
        width = max(COL_WIDTH, event.width // max(1, len(self.columns)))
        if width != self.col_width:
            self.col_width = width
            self.draw()

    def _card_lines(self, lesson):
        view = self.screen.state.view
        group = f", гр. {lesson['subgroup']}" if lesson["subgroup"] else ""
        if view == "teachers":
            first = f"{lesson['class_name']}{group}"
        elif view == "rooms":
            first = f"{lesson['class_name']}, {lesson['teacher_short']}"
        else:
            first = f"{lesson['teacher_short']}{group}"
        lines = [first]
        if view != "rooms":
            lines.append(f"каб. {lesson['room_number']}" if lesson["room_number"] else "без кабинета")
        level = self.levels.get(lesson["id"])
        if level:
            lines.append("Накладка" if level[0] == CONFLICT else "Проверьте")
        return lines

    def _card_height(self, lesson):
        return self.bold.metrics("linespace") + self.line * len(self._card_lines(lesson)) + 8

    def _layout(self):
        self.row_tops = []
        y = 0
        for slot in self.slots:
            self.row_tops.append(y)
            height = MIN_ROW_HEIGHT
            for i in range(len(self.columns)):
                cards = self.by_cell.get((i, slot["id"]), [])
                total = sum(self._card_height(x) + CARD_GAP for x in cards) + CARD_GAP
                height = max(height, total)
            y += height
        self.rows_bottom = y

    def draw(self):
        for canvas in (self.head, self.side, self.body, self.corner):
            canvas.delete("all")
        self.cards = []
        width = self.col_width * len(self.columns)
        total_height = self.rows_bottom + (SCORE_HEIGHT if self.scores else 0)
        border, muted, text = c["border"], c["muted"], c["text"]

        self.corner.create_text(10, HEAD_HEIGHT / 2, text="Урок", anchor="w", font=font(10, True), fill=text)
        self.corner.create_line(0, HEAD_HEIGHT - 1, self.side_width, HEAD_HEIGHT - 1, fill=border)
        for i, col in enumerate(self.columns):
            x = i * self.col_width
            cx = x + self.col_width / 2
            title = _fit(col.title, self.bold, self.col_width - 8)
            if col.subtitle:
                self.head.create_text(cx, 15, text=title, font=font(10, True), fill=text)
                self.head.create_text(cx, 31, text=_fit(col.subtitle, self.small, self.col_width - 8), font=font(9), fill=muted)
            else:
                self.head.create_text(cx, HEAD_HEIGHT / 2, text=title, font=font(10, True), fill=text)
            self.head.create_line(x + self.col_width - 1, 0, x + self.col_width - 1, HEAD_HEIGHT, fill=border)
        self.head.create_line(0, HEAD_HEIGHT - 1, width, HEAD_HEIGHT - 1, fill=border)

        for r, slot in enumerate(self.slots):
            top = self.row_tops[r]
            bottom = self._row_bottom(r)
            self.side.create_text(10, top + 16, text=f"{slot['number']} урок", anchor="w", font=font(10, True), fill=text)
            if slot["starts_at"]:
                span = f"{slot['starts_at']}–{slot['ends_at'] or ''}"
                self.side.create_text(10, top + 34, text=span, anchor="w", font=font(8), fill=muted)
            self.side.create_line(0, bottom - 1, self.side_width, bottom - 1, fill=border)
            for i, col in enumerate(self.columns):
                self._draw_cell(i, col, slot, top, bottom)
        for i in range(len(self.columns)):
            x = (i + 1) * self.col_width - 1
            self.body.create_line(x, 0, x, total_height, fill=border)
        if self.scores:
            self._draw_scores()
        self.head.configure(scrollregion=(0, 0, width, HEAD_HEIGHT))
        self.side.configure(scrollregion=(0, 0, self.side_width, total_height))
        self.body.configure(scrollregion=(0, 0, width, total_height))

    def _row_bottom(self, r):
        return self.row_tops[r + 1] if r + 1 < len(self.row_tops) else self.rows_bottom

    def _draw_cell(self, i, col, slot, top, bottom):
        x1, x2 = i * self.col_width, (i + 1) * self.col_width
        state = self.screen.cell_state(col, slot["id"])
        fill = {"free": c["ok_soft"], "warn": c["warn_soft"], "bad": c["conflict_soft"]}.get(state[0])
        if fill:
            self.body.create_rectangle(x1, top, x2 - 1, bottom - 1, fill=fill, outline="")
        self.body.create_line(x1, bottom - 1, x2, bottom - 1, fill=c["border"])
        cards = self.by_cell.get((i, slot["id"]), [])
        y = top + CARD_GAP
        for lesson in cards:
            y = self._draw_card(lesson, x1 + CARD_GAP, y, x2 - CARD_GAP - 1) + CARD_GAP
        if state[1] and not cards:
            color = {"free": c["ok"], "warn": c["warn"], "bad": c["conflict"]}[state[0]]
            self.body.create_text((x1 + x2) / 2, (top + bottom) / 2, text=state[1], font=font(9), fill=color, width=self.col_width - 12, justify="center")
        elif not cards and not self.screen.state.pick:
            self.body.create_text(
                (x1 + x2) / 2, (top + bottom) / 2, text="+ Добавить", font=font(9), fill=c["accent"],
                state="hidden", tags=(f"add_{i}_{slot['id']}",),
            )

    def _draw_card(self, lesson, x1, y1, x2):
        level = self.levels.get(lesson["id"])
        fill, outline, accent = c["accent_soft"], c["accent_soft"], None
        if level:
            conflict = level[0] == CONFLICT
            fill = c["conflict_soft"] if conflict else c["warn_soft"]
            outline = accent = c["conflict"] if conflict else c["warn"]
        if lesson["id"] in self.screen.state.flash:
            outline = c["accent"]
        y2 = y1 + self._card_height(lesson)
        width = 3 if lesson["id"] in self.screen.state.flash else 1
        self.body.create_rectangle(x1, y1, x2, y2, fill=fill, outline=outline, width=width)
        inner = x2 - x1 - 12
        y = y1 + 3
        self.body.create_text(x1 + 6, y, text=_fit(lesson["subject_short"], self.bold, inner), anchor="nw", font=font(10, True), fill=c["text"])
        y += self.bold.metrics("linespace")
        lines = self._card_lines(lesson)
        for n, line_text in enumerate(lines):
            is_flag = bool(level) and n == len(lines) - 1
            self.body.create_text(
                x1 + 6, y, text=_fit(line_text, self.small, inner), anchor="nw",
                font=font(9, is_flag), fill=accent if is_flag else c["muted"],
            )
            y += self.line
        self.cards.append((x1, y1, x2, y2, lesson))
        return y2

    def _draw_scores(self):
        top = self.rows_bottom
        self.side.create_rectangle(0, top, self.side_width, top + SCORE_HEIGHT, fill=c["bg"], outline="")
        self.side.create_text(10, top + SCORE_HEIGHT / 2, text="Баллы дня", anchor="w", font=font(9, True), fill=c["text"])
        most = max(self.scores + [1])
        for i, value in enumerate(self.scores):
            x = i * self.col_width
            self.body.create_rectangle(x, top, x + self.col_width - 1, top + SCORE_HEIGHT, fill=c["bg"], outline="")
            self.body.create_text(x + 8, top + 14, text=str(value), anchor="w", font=font(9), fill=c["text"])
            bar = self.col_width - 16
            self.body.create_rectangle(x + 8, top + 26, x + 8 + bar, top + 31, fill=c["border"], outline="")
            self.body.create_rectangle(x + 8, top + 26, x + 8 + bar * value / most, top + 31, fill=c["accent"], outline="")

    def card_at(self, x, y):
        for x1, y1, x2, y2, lesson in self.cards:
            if x1 <= x <= x2 and y1 <= y <= y2:
                return lesson
        return None

    def cell_at(self, x, y):
        """Столбец и слот по координатам холста, None вне сетки."""
        col = int(x // self.col_width)
        if not (0 <= col < len(self.columns)) or not (0 <= y < self.rows_bottom):
            return None
        row = bisect.bisect_right(self.row_tops, y) - 1
        return self.columns[col], self.slots[row]["id"], col

    def cell_at_root(self, x_root, y_root):
        x = self.body.canvasx(x_root - self.body.winfo_rootx())
        y = self.body.canvasy(y_root - self.body.winfo_rooty())
        inside = self.winfo_containing(x_root, y_root) is self.body
        return self.cell_at(x, y) if inside else None

    def _xy(self, event):
        return self.body.canvasx(event.x), self.body.canvasy(event.y)

    def _on_press(self, event):
        x, y = self._xy(event)
        self.press = (x, y, self.card_at(x, y))
        self.dragging = False
        self._hide_tip()

    def _on_drag(self, event):
        if not self.press or not self.press[2]:
            return
        x, y = self._xy(event)
        if not self.dragging and (abs(x - self.press[0]) > DRAG_THRESHOLD or abs(y - self.press[1]) > DRAG_THRESHOLD):
            self.dragging = True
            self.body.configure(cursor="fleur")
        if self.dragging:
            self.show_drop_target(self.cell_at(x, y))

    def show_drop_target(self, cell):
        self.body.delete("target")
        if cell:
            _col, slot_id, i = cell
            r = next(n for n, s in enumerate(self.slots) if s["id"] == slot_id)
            self.body.create_rectangle(
                i * self.col_width + 1, self.row_tops[r] + 1, (i + 1) * self.col_width - 2, self._row_bottom(r) - 2,
                outline=c["accent"], width=2, dash=(4, 3), tags=("target",),
            )

    def _on_release(self, event):
        press, self.press = self.press, None
        if not press:
            return
        x, y = self._xy(event)
        self.body.configure(cursor="")
        cell = self.cell_at(x, y)
        if self.dragging:
            self.dragging = False
            self.body.delete("target")
            if cell:
                self.screen.move_lesson(press[2], cell[0], cell[1])
            return
        if press[2]:
            self.screen.lesson_clicked(press[2], cell)
        elif cell:
            self.screen.cell_clicked(cell[0], cell[1])

    def _on_motion(self, event):
        x, y = self._xy(event)
        self.body.itemconfigure("hover_add", state="hidden")
        self.body.dtag("hover_add", "hover_add")
        cell = self.cell_at(x, y)
        if cell:
            tag = f"add_{cell[2]}_{cell[1]}"
            self.body.addtag_withtag("hover_add", tag)
            self.body.itemconfigure(tag, state="normal")
        key = self.card_at(x, y)
        hover = key["id"] if key else None
        if hover != self.hover:
            self.hover = hover
            self._hide_tip()
            if key and widgets.tips_enabled:
                level = self.levels.get(key["id"])
                prefix = level[1] + ". " if level else ""
                text = f"{prefix}Нажмите, чтобы изменить, или перетащите на другое место"
                self.tip_job = self.after(TIP_DELAY_MS, lambda: self._show_tip(text))

    def _on_leave(self, _event):
        self.body.itemconfigure("hover_add", state="hidden")
        self.hover = None
        self._hide_tip()

    def _show_tip(self, text):
        self.tip_job = None
        self.tip_window = tk.Toplevel(self)
        self.tip_window.wm_overrideredirect(True)
        self.tip_window.attributes("-topmost", True)
        tk.Label(
            self.tip_window, text=text, bg=c["tip_bg"], fg=c["tip_fg"], font=font(9), padx=8, pady=4,
            wraplength=300, justify="left",
        ).pack()
        self.tip_window.wm_geometry(f"+{self.winfo_pointerx() + 12}+{self.winfo_pointery() + 16}")

    def _hide_tip(self):
        if self.tip_job:
            self.after_cancel(self.tip_job)
            self.tip_job = None
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None

    def restore_position(self, pos):
        self.update_idletasks()
        self.body.xview_moveto(pos[0])
        self.body.yview_moveto(pos[1])

    def reveal(self, lesson_ids):
        for x1, y1, _x2, _y2, lesson in self.cards:
            if lesson["id"] in lesson_ids:
                width = max(1, self.col_width * len(self.columns))
                height = max(1, self.rows_bottom)
                self.update_idletasks()
                self.body.xview_moveto(max(0, x1 - 40) / width)
                self.body.yview_moveto(max(0, y1 - 40) / height)
                return
