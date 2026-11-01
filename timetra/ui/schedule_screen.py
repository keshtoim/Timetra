import tkinter as tk
from dataclasses import dataclass, field

from timetra.services.autoplace import auto_place, pick_room
from timetra.services.checks import CONFLICT, check_placement, day_score, find_problems
from timetra.ui.dialogs import Dialog, FormDialog, info_dialog
from timetra.ui.schedule_grid import Column, ScheduleGrid
from timetra.ui.theme import colors as c
from timetra.ui.theme import font
from timetra.ui.widgets import Btn, Scroll, Seg, Select, badge, label, note, tip

ODD, EVEN = 1, 2


@dataclass
class ScheduleState:
    week: int = ODD
    day: int = 1
    view: str = "classes"
    class_id: int | None = None
    shift: int = 1
    pick: int | None = None
    both: bool = True
    flash: set = field(default_factory=set)
    grid_pos: tuple = (0.0, 0.0)


class ScheduleScreen(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=c["bg"])
        self.app = app
        self.repo = app.repo
        self.state = app.schedule_state
        self.version = app.version_id
        self.grid_view = None
        self.workload_by_id = {w["id"]: w for w in self.repo.workload(self.version)}
        if self.state.pick not in self.workload_by_id:
            self.state.pick = None
        self.problems = find_problems(self.repo, self.version)
        self._build_head()
        self._build_tools()
        if self.state.pick:
            self._build_pickbar()
        self._build_work()
        app.bind("<Escape>", lambda _e: self.unpick())

    def _build_head(self):
        row = tk.Frame(self, bg=c["bg"])
        row.pack(fill="x", pady=(0, 8))
        label(row, "Расписание", 15, True).pack(side="left")
        Btn(
            row, "Отменить", "undo", self.app.undo, disabled=not self.app.undo_stack,
            tooltip="Вернуть как было до последнего изменения",
        ).pack(side="right")
        conflicts = sum(p.severity == CONFLICT for p in self.problems)
        if conflicts:
            Btn(row, f"Накладок: {conflicts}", "warning", lambda: self.app.go("check"), "danger", "Открыть список ошибок").pack(side="right", padx=8)
        elif self.problems:
            Btn(row, f"Предупреждений: {len(self.problems)}", "warning", lambda: self.app.go("check"), tooltip="Открыть список предупреждений").pack(side="right", padx=8)
        else:
            badge(row, "Ошибок нет", "ok", "check").pack(side="right", padx=8)

    def _build_tools(self):
        s = self.state
        box = tk.Frame(self, bg=c["surface"], highlightthickness=1, highlightbackground=c["border"], padx=10, pady=8)
        box.pack(fill="x", pady=(0, 8))
        versions = self.repo.versions()
        first = self._tool_row(box)
        label(first, "Вариант", 9, color="muted", bg="surface").pack(side="left", padx=(0, 6))
        Select(
            first, [(v["id"], v["name"] + (" (действующий)" if v["is_active"] else "")) for v in versions],
            self.version, self._set_version, tooltip="Можно хранить несколько вариантов расписания и сравнивать их",
        ).pack(side="left")
        Btn(first, "Копия варианта", "copy", self._copy_version, tooltip="Создать копию этого варианта, чтобы пробовать изменения").pack(side="left", padx=8)
        if not next(v for v in versions if v["id"] == self.version)["is_active"]:
            Btn(first, "Сделать действующим", "star", self._activate, tooltip="Этот вариант будет считаться настоящим расписанием школы").pack(side="left")

        second = self._tool_row(box)
        if s.view != "all":
            label(second, "Неделя", 9, color="muted", bg="surface").pack(side="left", padx=(0, 6))
            Seg(second, [(ODD, "Нечётная", "Показать нечётную неделю"), (EVEN, "Чётная", "Показать чётную неделю")], s.week, lambda v: self._set("week", v)).pack(side="left", padx=(0, 14))
        label(second, "Показать", 9, color="muted", bg="surface").pack(side="left", padx=(0, 6))
        Seg(
            second,
            [
                ("all", "Всё расписание", "Все классы за всю неделю, чётная и нечётная недели в одной клетке"),
                ("classes", "Все классы", "Все классы за один день"), ("week", "Один класс", "Вся неделя одного класса"),
                ("teachers", "Учителя", "Расписание по учителям"), ("rooms", "Кабинеты", "Занятость кабинетов"),
            ],
            s.view, lambda v: self._set("view", v),
        ).pack(side="left")
        classes = self.repo.classes()
        if s.view == "week" and classes:
            if s.class_id not in [x["id"] for x in classes]:
                s.class_id = classes[0]["id"]
            Select(second, [(x["id"], x["name"]) for x in classes], s.class_id, lambda v: self._set("class_id", v), width=8).pack(side="left", padx=8)

        used = sorted({x["shift_id"] for x in classes})
        if s.view == "classes" or s.view == "teachers" or s.view == "rooms" or (s.view == "all" and len(used) > 1):
            third = self._tool_row(box)
            if len(used) > 1 and s.view != "week":
                if s.shift not in used:
                    s.shift = used[0]
                names = {x["id"]: x["name"] for x in self.repo.shifts()}
                label(third, "Смена", 9, color="muted", bg="surface").pack(side="left", padx=(0, 6))
                Seg(third, [(i, names[i]) for i in used], s.shift, lambda v: self._set("shift", v)).pack(side="left", padx=(0, 14))
            if s.view != "all":
                s.day = min(s.day, self._last_day())
                label(third, "День", 9, color="muted", bg="surface").pack(side="left", padx=(0, 6))
                days = [(d["id"], d["name"]) for d in self.repo.weekdays() if d["id"] <= self._last_day()]
                Seg(third, days, s.day, lambda v: self._set("day", v)).pack(side="left")

    def _last_day(self):
        return 6 if any(x["study_days"] == 6 for x in self.repo.classes()) else 5

    def _tool_row(self, box):
        row = tk.Frame(box, bg=c["surface"])
        row.pack(fill="x", pady=2)
        return row

    def _build_pickbar(self):
        wl = self.workload_by_id[self.state.pick]
        bar = tk.Frame(self, bg=c["accent_soft"], padx=10, pady=6)
        bar.pack(fill="x", pady=(0, 8))
        text = f"{self._wl_title(wl)}: выберите клетку. Зелёная — свободно, жёлтая — есть предупреждение, красная — накладка."
        label(bar, text, bg="accent_soft", wraplength=760, justify="left").pack(side="left")
        Btn(bar, "Отменить выбор", "close", self.unpick).pack(side="right")

    def _build_work(self):
        work = tk.Frame(self, bg=c["bg"])
        work.pack(fill="both", expand=True)
        self._build_panel(work)
        columns, slots = self._columns()
        if not columns or not slots:
            self._build_empty(work)
            return
        levels = {}
        for problem in self.problems:
            for lesson_id in problem.lesson_ids:
                if problem.severity == CONFLICT or lesson_id not in levels:
                    levels[lesson_id] = (problem.severity, problem.title)
        whole = self.state.view == "all"
        lessons = self.repo.lessons(self.version, None if whole else self.state.week)
        scores = None
        if self.state.view in ("classes", "week"):
            scores = [day_score(lessons, col.class_id, self.state.week, col.day) for col in columns]
        days = [d for d in self.repo.weekdays() if d["id"] <= self._last_day()] if whole else None
        self.grid_view = ScheduleGrid(work, self, columns, slots, lessons, levels, scores, days)
        self.grid_view.pack(side="left", fill="both", expand=True)
        self.grid_view.restore_position(self.state.grid_pos)
        if self.state.flash:
            self.grid_view.reveal(self.state.flash)

    def _build_empty(self, parent):
        box = tk.Frame(parent, bg=c["bg"])
        box.pack(side="left", fill="both", expand=True)
        label(box, "Здесь появится сетка расписания. Сначала добавьте классы, учителей и предметы.", color="muted").pack(pady=(40, 10))
        Btn(box, "Открыть справочники", "list", lambda: self.app.go("refs")).pack()

    def _build_panel(self, parent):
        s = self.state
        items = list(self.workload_by_id.values())
        if s.view == "week":
            items = [w for w in items if w["class_id"] == s.class_id]
        items = [w for w in items if self._left(w) > 0]
        total = sum(self._left(w) for w in items)
        panel = tk.Frame(parent, bg=c["surface"], highlightthickness=1, highlightbackground=c["border"], width=250)
        panel.pack(side="right", fill="y", padx=(10, 0))
        panel.pack_propagate(False)
        head = tk.Frame(panel, bg=c["surface"])
        head.pack(fill="x", padx=10, pady=(8, 4))
        label(head, "Ещё не поставлено", 10, True, bg="surface").pack(side="left")
        badge(head, str(total), "warning" if total else "ok").pack(side="right")
        if not total:
            note(panel, "Все уроки поставлены" if self.workload_by_id else "Нагрузка пока пуста", "ok" if self.workload_by_id else "neutral").pack(fill="x", padx=10, pady=4)
            return
        label(
            panel, "Перетащите урок в сетку или нажмите на него, а потом на клетку.", 9, color="muted", bg="surface",
            wraplength=226, justify="left", anchor="w",
        ).pack(fill="x", padx=10)
        self.both_var = tk.BooleanVar(value=s.both)
        check = tk.Checkbutton(
            panel, text="На обе недели", variable=self.both_var, command=self._set_both, font=font(), bg=c["surface"],
            fg=c["text"], selectcolor=c["surface"], activebackground=c["surface"], activeforeground=c["text"], anchor="w",
        )
        check.pack(fill="x", padx=6)
        tip(check, "Обычно урок идёт каждую неделю. Снимите галочку для предмета раз в две недели")
        Btn(panel, "Расставить автоматически", "wand", self._auto, tooltip="Программа сама поставит оставшиеся уроки туда, где нет накладок").pack(fill="x", padx=10, pady=(4, 6))
        scroll = Scroll(panel, bg="surface")
        scroll.pack(fill="both", expand=True, padx=(10, 0), pady=(0, 8))
        for wl in items:
            self._panel_item(scroll.inner, wl)

    def _panel_item(self, parent, wl):
        selected = self.state.pick == wl["id"]
        bg = c["accent_soft"] if selected else c["surface"]
        border = c["accent"] if selected else c["border"]
        row = tk.Frame(parent, bg=bg, highlightthickness=1, highlightbackground=border, cursor="hand2")
        row.pack(fill="x", pady=(0, 4), padx=(0, 6))
        title = tk.Label(row, text=f"{wl['subject_name']} × {self._left(wl)}", font=font(10, True), fg=c["text"], bg=bg, anchor="w", padx=7)
        title.pack(fill="x", pady=(3, 0))
        group = f", гр. {wl['subgroup']}" if wl["subgroup"] else ""
        sub = tk.Label(row, text=f"{wl['class_name']}{group} · {wl['teacher_short']}", font=font(9), fg=c["muted"], bg=bg, anchor="w", padx=7)
        sub.pack(fill="x", pady=(0, 3))
        for part in (row, title, sub):
            part.bind("<ButtonPress-1>", lambda e: self._panel_press(e))
            part.bind("<B1-Motion>", lambda e, w=wl["id"]: self._panel_drag(e, w))
            part.bind("<ButtonRelease-1>", lambda e, w=wl["id"]: self._panel_release(e, w))
        tip(row, f"Осталось поставить: {self._left(wl)} за две недели")

    def _panel_press(self, event):
        self.panel_press = (event.x_root, event.y_root)
        self.panel_dragging = False

    def _panel_drag(self, event, _wl_id):
        if abs(event.x_root - self.panel_press[0]) + abs(event.y_root - self.panel_press[1]) > 6:
            self.panel_dragging = True
            event.widget.configure(cursor="fleur")
        if self.panel_dragging and self.grid_view:
            self.grid_view.show_drop_target(self.grid_view.cell_at_root(event.x_root, event.y_root))

    def _panel_release(self, event, wl_id):
        if not self.panel_dragging:
            self.state.pick = None if self.state.pick == wl_id else wl_id
            self.app.refresh()
            return
        event.widget.configure(cursor="hand2")
        if self.grid_view:
            cell = self.grid_view.cell_at_root(event.x_root, event.y_root)
            self.grid_view.show_drop_target(None)
            if cell and self.grid_view.split:
                self.state.week = self.grid_view.week_at_root(event.x_root)
            if cell:
                self.place(wl_id, cell[0], cell[1])

    def _left(self, wl):
        return max(0, wl["lessons_per_fortnight"] - wl["placed"])

    def _wl_title(self, wl):
        group = f" (гр. {wl['subgroup']})" if wl["subgroup"] else ""
        return f"{wl['class_name']}, {wl['subject_name']}{group}"

    def _columns(self):
        s = self.state
        shift = s.shift
        if s.view == "week":
            match = next((x for x in self.repo.classes() if x["id"] == s.class_id), None)
            if not match:
                return [], []
            days = [d for d in self.repo.weekdays() if d["id"] <= match["study_days"]]
            return [Column(d["name"], "", d["id"], class_id=match["id"]) for d in days], self.repo.slots(match["shift_id"])
        slots = self.repo.slots(shift)
        if s.view in ("classes", "all"):
            columns = [
                Column(x["name"], f"{x['students_count']} уч." if x["students_count"] else "", s.day, class_id=x["id"])
                for x in self.repo.classes(shift)
            ]
        elif s.view == "teachers":
            columns = [Column(t["short"], "", s.day, teacher_id=t["id"]) for t in self.repo.teachers()]
        else:
            columns = [Column(r["number"], r["type_name"], s.day, room_id=r["id"]) for r in self.repo.rooms()]
        return columns, slots

    def _set(self, name, value):
        setattr(self.state, name, value)
        self.state.grid_pos = (0.0, 0.0)
        self.app.refresh()

    def _set_both(self):
        self.state.both = self.both_var.get()
        self.app.refresh()

    def _set_version(self, value):
        self.app.version_id = value
        self.state.pick = None
        self.app.refresh()

    def _copy_version(self):
        name = next(v["name"] for v in self.repo.versions() if v["id"] == self.version)
        fields = [{"key": "name", "label": "Название", "required": True, "value": f"{name} (копия)"}]

        def check(v):
            return "Такое название уже есть" if any(x["name"] == v["name"] for x in self.repo.versions()) else None

        def save(v):
            def action():
                self.app.version_id = self.repo.copy_version(self.version, v["name"])
            self.app.mutate("Копия создана и открыта", action)

        FormDialog(self.app, "Копия варианта", fields, check, save)

    def _activate(self):
        self.app.mutate("Этот вариант теперь действующий", lambda: self.repo.set_active_version(self.version))

    def _auto(self):
        placed = [0]

        def action():
            placed[0] = auto_place(self.repo, self.version, self.state.class_id if self.state.view == "week" else None)

        self.state.pick = None
        self.app.mutate("Расстановка выполнена", action)
        self.app.toast(
            f"Поставлено уроков: {placed[0]}" if placed[0] else "Свободных мест без накладок не нашлось",
            can_undo=bool(placed[0]),
        )

    def unpick(self):
        if self.state.pick:
            self.state.pick = None
            self.app.refresh()

    def cell_state(self, col, slot_id):
        """(вид подсветки, подпись) для клетки в режиме выбора места."""
        if not self.state.pick:
            return (None, None)
        wl = self.workload_by_id[self.state.pick]
        if (col.class_id and col.class_id != wl["class_id"]) or (col.teacher_id and col.teacher_id != wl["teacher_id"]):
            return (None, None)
        weeks = self._weeks(wl)
        results = [check_placement(self.repo, self.version, wl, w, col.day, slot_id, col.room_id) for w in weeks]
        if any(r.room_busy for r in results):
            return ("bad", "Кабинет занят")
        if any(r.conflicts for r in results):
            return ("bad", "Будет накладка")
        if any(r.warnings for r in results):
            return ("warn", "Учитель занят" if any("занят" in t for r in results for t in r.warnings) else "Есть предупреждение")
        return ("free", "Поставить сюда")

    def _weeks(self, wl):
        return (ODD, EVEN) if self.state.both and self._left(wl) >= 2 else (self.state.week,)

    def place(self, wl_id, col, slot_id):
        wl = self.repo.workload_item(self.version, wl_id)
        if col.class_id and col.class_id != wl["class_id"]:
            self.app.toast(f"Это урок класса {wl['class_name']}. Поставьте его в столбец своего класса.")
            return
        if col.teacher_id and col.teacher_id != wl["teacher_id"]:
            self.app.toast(f"Этот урок ведёт {wl['teacher_short']}. Поставьте его в столбец этого учителя.")
            return
        if self._left(wl) <= 0:
            self.app.toast("Этот урок уже поставлен столько раз, сколько указано в нагрузке.")
            return
        weeks = self._weeks(wl)
        room = col.room_id or pick_room(self.repo, wl, self.version, weeks, col.day, slot_id)
        results = [check_placement(self.repo, self.version, wl, w, col.day, slot_id, room) for w in weeks]
        busy = next((r.room_busy for r in results if r.room_busy), None)
        if busy:
            info_dialog(self.app, "Кабинет занят", f"{busy}. Выберите другой кабинет или другое время.", "conflict")
            return
        issues = [t for r in results for t in (*r.conflicts, *r.warnings)]
        if self.state.pick == wl_id and self._left(wl) - len(weeks) <= 0:
            self.state.pick = None

        def action():
            for week in weeks:
                self.repo.add_lesson(self.version, wl_id, week, col.day, slot_id, room)

        message = f"Урок поставлен. Обратите внимание: {issues[0]}" if issues else "Урок поставлен"
        self.app.mutate(message, action)

    def move_lesson(self, lesson, col, slot_id):
        if col.class_id and col.class_id != lesson["class_id"]:
            self.app.toast(f"Это урок класса {lesson['class_name']}, его нельзя перенести в другой класс.")
            return
        if col.teacher_id and col.teacher_id != lesson["teacher_id"]:
            self.app.toast(f"Этот урок ведёт {lesson['teacher_short']}. Сменить учителя можно в разделе «Нагрузка».")
            return
        same_place = lesson["weekday_id"] == col.day and lesson["lesson_slot_id"] == slot_id
        if same_place and (not col.room_id or col.room_id == lesson["classroom_id"]):
            return
        wl = self.repo.workload_item(self.version, lesson["workload_id"])
        twin = self.repo.lesson_twin(lesson)
        rows = [lesson, twin] if twin else [lesson]
        ids = [r["id"] for r in rows]
        results = [
            check_placement(self.repo, self.version, wl, r["week_type_id"], col.day, slot_id, col.room_id or r["classroom_id"], ids)
            for r in rows
        ]
        busy = next((r.room_busy for r in results if r.room_busy), None)
        if busy:
            info_dialog(self.app, "Кабинет занят", f"{busy}. Нажмите на урок и выберите другой кабинет.", "conflict")
            return
        issues = [t for r in results for t in (*r.conflicts, *r.warnings)]

        def action():
            for r in rows:
                self.repo.move_lesson(r["id"], col.day, slot_id, col.room_id or r["classroom_id"])

        self.app.mutate(f"Урок перенесён. Обратите внимание: {issues[0]}" if issues else "Урок перенесён", action)

    def lesson_clicked(self, lesson, cell):
        if self.state.pick and cell:
            self.place(self.state.pick, cell[0], cell[1])
        else:
            LessonDialog(self, lesson=lesson)

    def cell_clicked(self, col, slot_id):
        if self.state.pick:
            self.place(self.state.pick, col, slot_id)
        else:
            LessonDialog(self, col=col, slot_id=slot_id)


class LessonDialog(Dialog):
    def __init__(self, screen, lesson=None, col=None, slot_id=None):
        self.screen = screen
        self.repo = screen.repo
        self.lesson = lesson
        self.twin = self.repo.lesson_twin(lesson) if lesson else None
        self.day = lesson["weekday_id"] if lesson else col.day
        self.slot_id = lesson["lesson_slot_id"] if lesson else slot_id
        self.week = lesson["week_type_id"] if lesson else screen.state.week
        items = list(screen.workload_by_id.values())
        if lesson:
            current = screen.workload_by_id[lesson["workload_id"]]
            candidates = [current, *[w for w in items if w["class_id"] == current["class_id"] and w["id"] != current["id"] and screen._left(w) > 0]]
        else:
            candidates = [
                w for w in items
                if screen._left(w) > 0
                and (not col.class_id or w["class_id"] == col.class_id)
                and (not col.teacher_id or w["teacher_id"] == col.teacher_id)
            ]
        if not candidates:
            info_dialog(screen.app, "Нет уроков для этой клетки", "Все уроки из нагрузки уже поставлены. Чтобы добавить новый, откройте раздел «Нагрузка».", "neutral")
            return
        super().__init__(screen.app, "Изменить урок" if lesson else "Поставить урок")
        day_name = next(d["name"] for d in self.repo.weekdays() if d["id"] == self.day)
        number = next(s["number"] for s in self.repo.slots() if s["id"] == self.slot_id)
        week_name = next(w["name"] for w in self.repo.week_types() if w["id"] == self.week)
        label(self.body, f"{day_name}, {number} урок · {week_name.lower()} неделя", 9, color="muted", bg="surface", anchor="w").pack(fill="x", pady=(0, 8))

        self.title_field("Какой урок")
        first = candidates[0]
        self.wl_select = Select(
            self.body, [(w["id"], f"{screen._wl_title(w)} · {w['teacher_short']}") for w in candidates],
            first["id"], lambda _v: self.update_notes(), width=44,
        )
        self.wl_select.pack(fill="x", pady=(0, 8))

        self.title_field("Кабинет")
        if lesson:
            room = lesson["classroom_id"]
        elif col.room_id:
            room = col.room_id
        else:
            room = pick_room(self.repo, first, screen.version, self._weeks_for(True), self.day, self.slot_id)
        self.room_select = Select(
            self.body, [(None, "Выбрать позже"), *[(r["id"], f"{r['number']} ({r['type_name']})") for r in self.repo.rooms()]],
            room, lambda _v: self.update_notes(), width=44,
        )
        self.room_select.pack(fill="x", pady=(0, 8))

        self.title_field("На каких неделях")
        both_default = bool(self.twin) if lesson else screen.state.both
        self.weeks_select = Select(
            self.body, [("both", "Обе недели"), ("one", f"Только {week_name.lower()}")],
            "both" if both_default else "one", lambda _v: self.update_notes(), width=44,
        )
        self.weeks_select.pack(fill="x", pady=(0, 8))

        self.notes = tk.Frame(self.body, bg=c["surface"])
        self.notes.pack(fill="x")
        row = self.footer()
        Btn(row, "Сохранить", "check", self.save, "primary").pack(side="right")
        Btn(row, "Отмена", None, self.destroy).pack(side="right", padx=(0, 8))
        if lesson:
            Btn(row, "Убрать из расписания", "delete", self.remove, "danger").pack(side="left")
        self.update_notes()
        self.show()

    def title_field(self, text):
        label(self.body, text, 9, color="muted", bg="surface", anchor="w").pack(fill="x")

    def _weeks_for(self, both):
        return (ODD, EVEN) if both else (self.week,)

    def _skip(self):
        ids = []
        if self.lesson:
            ids.append(self.lesson["id"])
        if self.twin:
            ids.append(self.twin["id"])
        return ids

    def _check(self):
        wl = self.screen.workload_by_id[self.wl_select.value()]
        weeks = self._weeks_for(self.weeks_select.value() == "both")
        return [
            check_placement(self.repo, self.screen.version, wl, w, self.day, self.slot_id, self.room_select.value(), self._skip())
            for w in weeks
        ]

    def update_notes(self):
        for child in self.notes.winfo_children():
            child.destroy()
        results = self._check()
        shown = set()
        for result in results:
            for kind, texts in (("conflict", [result.room_busy] if result.room_busy else []), ("conflict", result.conflicts), ("warning", result.warnings)):
                for text in texts:
                    if text not in shown:
                        shown.add(text)
                        note(self.notes, text, kind).pack(fill="x", pady=(0, 4))
        if not shown:
            kind, text = ("neutral", "Кабинет можно выбрать позже") if not self.room_select.value() else ("ok", "Накладок нет")
            note(self.notes, text, kind).pack(fill="x", pady=(0, 4))

    def save(self):
        if any(r.room_busy for r in self._check()):
            self.update_notes()
            return
        wl_id = self.wl_select.value()
        room = self.room_select.value()
        weeks = self._weeks_for(self.weeks_select.value() == "both")
        skip = self._skip()
        version, day, slot = self.screen.version, self.day, self.slot_id
        self.destroy()

        def action():
            self.repo.delete_lessons(skip)
            for week in weeks:
                self.repo.add_lesson(version, wl_id, week, day, slot, room)

        self.screen.app.mutate("Урок изменён" if self.lesson else "Урок поставлен", action)

    def remove(self):
        skip = self._skip()
        self.destroy()
        self.screen.app.mutate("Урок убран из расписания", lambda: self.repo.delete_lessons(skip))
