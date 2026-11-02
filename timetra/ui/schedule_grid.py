import bisect
import tkinter as tk
from dataclasses import dataclass, replace
from tkinter import font as tkfont
from tkinter import ttk

from timetra.services.checks import CONFLICT
from timetra.ui import widgets
from timetra.ui.theme import colors as c
from timetra.ui.theme import font

ODD, EVEN = 1, 2
COL_WIDTH = 128
SPLIT_COL_WIDTH = 190  # две половины по неделям должны оставаться читаемыми
SIDE_WIDTH = 92
SPLIT_SIDE_WIDTH = 112
WEEK_TAGS = {ODD: "Нечётная", EVEN: "Чётная"}
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
    С days сетка показывает всю неделю: строка = день + урок, а клетка делится по типам недель.
    """

    def __init__(self, parent, screen, columns, slots, lessons, levels, scores=None, days=None):
        super().__init__(parent, bg=c["surface"], highlightthickness=1, highlightbackground=c["border"])
        self.screen = screen
        self.columns, self.slots = columns, slots
        self.levels = levels
        self.scores = scores
        self.split = bool(days)
        self.rows = [(d["id"], d["name"], s) for d in days for s in slots] if days else [(None, "", s) for s in slots]
        self.bold = tkfont.Font(font=font(10, True))
        self.small = tkfont.Font(font=font(9))
        self.line = self.small.metrics("linespace") + 1
        self.by_cell = {}
        row_index = {(day, s["id"]): r for r, (day, _name, s) in enumerate(self.rows)}
        for row in lessons:
            for i, col in enumerate(columns):
                if self._matches(row, col):
                    r = row_index.get((row["weekday_id"] if self.split else None, row["lesson_slot_id"]))
                    if r is not None:
                        self.by_cell.setdefault((i, r), []).append(row)
        base_side = SPLIT_SIDE_WIDTH if self.split else SIDE_WIDTH
        self.side_width = int(base_side * (self.bold.metrics("linespace") / 17))
        self.min_col = SPLIT_COL_WIDTH if self.split else COL_WIDTH
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
        self.col_width = self.min_col
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
        if not self.split and row["weekday_id"] != col.day:
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
        width = max(self.min_col, event.width // max(1, len(self.columns)))
        if width != self.col_width:
            self.col_width = width
            self.draw()

    def _cell_parts(self, cards):
        """Уроки клетки: (на обе недели, только нечётная, только чётная).

        Урок на обе недели хранится двумя строками, показываем его одной карточкой, если кабинет совпадает.
        """
        if not self.split:
            return [(x, None) for x in cards], [], []
        both, odd, even, used = [], [], [], set()
        for lesson in sorted(cards, key=lambda x: (x["subgroup"], x["week_type_id"])):
            if lesson["id"] in used:
                continue
            twin = next(
                (
                    x for x in cards
                    if x["workload_id"] == lesson["workload_id"] and x["week_type_id"] != lesson["week_type_id"]
                    and x["classroom_id"] == lesson["classroom_id"]
                ),
                None,
            )
            if twin:
                used.add(twin["id"])
                both.append((lesson, twin))
            else:
                (odd if lesson["week_type_id"] == ODD else even).append((lesson, None))
        return both, odd, even

    def _level(self, lesson, twin):
        levels = [self.levels[x["id"]] for x in (lesson, twin) if x and x["id"] in self.levels]
        return next((x for x in levels if x[0] == CONFLICT), levels[0] if levels else None)

    def _card_lines(self, lesson, twin=None, tag=None):
        view = self.screen.state.view
        group = f", гр. {lesson['subgroup']}" if lesson["subgroup"] else ""
        if view == "teachers":
            first = f"{lesson['class_name']}{group}"
        elif view == "rooms":
            first = f"{lesson['class_name']}, {lesson['teacher_short']}"
        else:
            first = f"{lesson['teacher_short']}{group}"
        lines = [tag, first] if tag else [first]
        if view != "rooms":
            lines.append(f"каб. {lesson['room_number']}" if lesson["room_number"] else "без кабинета")
        level = self._level(lesson, twin)
        if level:
            # третий элемент — своя пометка, например «Замена» на вкладке «На дату»
            lines.append(level[2] if len(level) > 2 else "Накладка" if level[0] == CONFLICT else "Проверьте")
        return lines

    def _card_height(self, lesson, twin=None, tag=None):
        return self.bold.metrics("linespace") + self.line * len(self._card_lines(lesson, twin, tag)) + 8

    def _stack_height(self, items, tag=None):
        return sum(self._card_height(x, twin, tag) + CARD_GAP for x, twin in items)

    def _layout(self):
        self.row_tops = []
        y = 0
        for r in range(len(self.rows)):
            self.row_tops.append(y)
            height = MIN_ROW_HEIGHT
            for i in range(len(self.columns)):
                both, odd, even = self._cell_parts(self.by_cell.get((i, r), []))
                halves = max(self._stack_height(odd, WEEK_TAGS[ODD]), self._stack_height(even, WEEK_TAGS[EVEN]))
                height = max(height, self._stack_height(both) + halves + CARD_GAP)
            y += height
        self.rows_bottom = y

    def draw(self):
        for canvas in (self.head, self.side, self.body, self.corner):
            canvas.delete("all")
        self.cards = []
        width = self.col_width * len(self.columns)
        total_height = self.rows_bottom + (SCORE_HEIGHT if self.scores else 0)
        border, muted, text = c["border"], c["muted"], c["text"]

        corner_title = "День и урок" if self.split else "Урок"
        self.corner.create_text(10, HEAD_HEIGHT / 2, text=corner_title, anchor="w", font=font(10, True), fill=text)
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

        for r, (day, day_name, slot) in enumerate(self.rows):
            top = self.row_tops[r]
            bottom = self._row_bottom(r)
            y = top + 16
            new_day = self.split and (r == 0 or self.rows[r - 1][0] != day)
            if new_day:
                self.side.create_text(10, y, text=day_name, anchor="w", font=font(10, True), fill=c["accent"])
                y += 18
            self.side.create_text(10, y, text=f"{slot['number']} урок", anchor="w", font=font(10, True), fill=text)
            if slot["starts_at"]:
                span = f"{slot['starts_at']}–{slot['ends_at'] or ''}"
                self.side.create_text(10, y + 18, text=span, anchor="w", font=font(8), fill=muted)
            self.side.create_line(0, bottom - 1, self.side_width, bottom - 1, fill=border)
            for i, col in enumerate(self.columns):
                self._draw_cell(i, r, self._col_for(col, day), slot, top, bottom)
            if new_day and r:
                # разделитель дней заметнее обычной линии
                self.side.create_line(0, top, self.side_width, top, fill=c["accent"], width=2)
                self.body.create_line(0, top, width, top, fill=c["accent"], width=2)
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

    def _col_for(self, col, day):
        return replace(col, day=day) if day else col

    def _draw_cell(self, i, r, col, slot, top, bottom):
        x1, x2 = i * self.col_width, (i + 1) * self.col_width
        state = self.screen.cell_state(col, slot["id"])
        fill = {"free": c["ok_soft"], "warn": c["warn_soft"], "bad": c["conflict_soft"]}.get(state[0])
        if fill:
            self.body.create_rectangle(x1, top, x2 - 1, bottom - 1, fill=fill, outline="")
        self.body.create_line(x1, bottom - 1, x2, bottom - 1, fill=c["border"])
        cards = self.by_cell.get((i, r), [])
        both, odd, even = self._cell_parts(cards)
        y = top + CARD_GAP
        for lesson, twin in both:
            y = self._draw_card(lesson, x1 + CARD_GAP, y, x2 - CARD_GAP - 1, twin) + CARD_GAP
        middle = (x1 + x2) // 2
        odd_y = even_y = y
        for lesson, _twin in odd:
            odd_y = self._draw_card(lesson, x1 + CARD_GAP, odd_y, middle - 1, None, WEEK_TAGS[ODD]) + CARD_GAP
        for lesson, _twin in even:
            even_y = self._draw_card(lesson, middle + 1, even_y, x2 - CARD_GAP - 1, None, WEEK_TAGS[EVEN]) + CARD_GAP
        if state[1] and not cards:
            color = {"free": c["ok"], "warn": c["warn"], "bad": c["conflict"]}[state[0]]
            self.body.create_text((x1 + x2) / 2, (top + bottom) / 2, text=state[1], font=font(9), fill=color, width=self.col_width - 12, justify="center")
        elif not cards and not self.screen.state.pick:
            self.body.create_text(
                (x1 + x2) / 2, (top + bottom) / 2, text="+ Добавить", font=font(9), fill=c["accent"],
                state="hidden", tags=(f"add_{i}_{r}",),
            )

    def _draw_card(self, lesson, x1, y1, x2, twin=None, tag=None):
        level = self._level(lesson, twin)
        fill, outline, accent = c["accent_soft"], c["accent_soft"], None
        if level:
            conflict = level[0] == CONFLICT
            fill = c["conflict_soft"] if conflict else c["warn_soft"]
            outline = accent = c["conflict"] if conflict else c["warn"]
        flash = lesson["id"] in self.screen.state.flash or (twin is not None and twin["id"] in self.screen.state.flash)
        if flash:
            outline = c["accent"]
        y2 = y1 + self._card_height(lesson, twin, tag)
        width = 3 if flash else 1
        self.body.create_rectangle(x1, y1, x2, y2, fill=fill, outline=outline, width=width)
        inner = x2 - x1 - 12
        y = y1 + 3
        self.body.create_text(x1 + 6, y, text=_fit(lesson["subject_short"], self.bold, inner), anchor="nw", font=font(10, True), fill=c["text"])
        y += self.bold.metrics("linespace")
        lines = self._card_lines(lesson, twin, tag)
        for n, line_text in enumerate(lines):
            is_flag = bool(level) and n == len(lines) - 1
            color = accent if is_flag else c["accent"] if tag and n == 0 else c["muted"]
            self.body.create_text(
                x1 + 6, y, text=_fit(line_text, self.small, inner), anchor="nw", font=font(9, is_flag), fill=color,
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
        day, _name, slot = self.rows[row]
        return self._col_for(self.columns[col], day), slot["id"], col, row

    def week_at(self, x):
        """Половина клетки под курсором: левая — нечётная неделя, правая — чётная."""
        return ODD if x % self.col_width < self.col_width / 2 else EVEN

    def week_at_root(self, x_root):
        return self.week_at(self.body.canvasx(x_root - self.body.winfo_rootx()))

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
            _col, _slot_id, i, r = cell
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
        if self.split:
            self.screen.state.week = self.week_at(x)
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
            tag = f"add_{cell[2]}_{cell[3]}"
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
