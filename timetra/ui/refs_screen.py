import tkinter as tk

from timetra.services.sanpin import fill_subjects, format_scores
from timetra.ui.dialogs import FormDialog, confirm_dialog, info_dialog
from timetra.ui.theme import colors as c
from timetra.ui.widgets import Btn, DataTable, Scroll, Seg, label

TABS = [
    ("teachers", "Учителя", "учителя"),
    ("classes", "Классы", "класс"),
    ("subjects", "Предметы", "предмет"),
    ("rooms", "Кабинеты", "кабинет"),
    ("slots", "Звонки", "урок"),
]
DAY_SHORT = {1: "Пн", 2: "Вт", 3: "Ср", 4: "Чт", 5: "Пт", 6: "Сб"}


class RefsScreen(tk.Frame):
    tab = "teachers"  # на уровне класса: вкладка не сбрасывается при обновлении экрана

    def __init__(self, parent, app):
        super().__init__(parent, bg=c["bg"])
        self.app = app
        self.repo = app.repo
        label(self, "Справочники", 15, True, anchor="w").pack(fill="x")
        label(self, "Основные данные школы. Их используют расписание и нагрузка.", color="muted", anchor="w").pack(fill="x", pady=(0, 10))
        row = tk.Frame(self, bg=c["bg"])
        row.pack(fill="x", pady=(0, 10))
        Seg(row, [(k, t) for k, t, _o in TABS], RefsScreen.tab, self._switch).pack(side="left")
        one = next(o for k, _t, o in TABS if k == RefsScreen.tab)
        Btn(row, f"Добавить {one}", "add", lambda: self.edit(None), "primary").pack(side="right")
        if RefsScreen.tab == "subjects":
            Btn(
                row, "Вернуть баллы СанПиН", "undo", self.reset_sanpin,
                tooltip="Заполнить баллы по таблицам 6.9–6.11 СанПиН 1.2.3685-21",
            ).pack(side="right", padx=(0, 8))
        scroll = Scroll(self)
        scroll.pack(fill="both", expand=True)
        columns, rows = getattr(self, f"_{RefsScreen.tab}_table")()
        if rows:
            DataTable(
                scroll.inner, columns, rows,
                [("Изменить", "edit", self.edit), ("Удалить", "delete", self.delete)],
            ).pack(fill="x")
        else:
            label(scroll.inner, f"Пока пусто. Нажмите «Добавить {one}».", color="muted").pack(anchor="w", pady=20)

    def _switch(self, tab):
        RefsScreen.tab = tab
        self.app.refresh()

    def edit(self, key):
        getattr(self, f"_{RefsScreen.tab}_form")(key)

    def delete(self, key):
        getattr(self, f"_{RefsScreen.tab}_delete")(key)

    def _ask_delete(self, title, action):
        confirm_dialog(
            self.app, "Удалить?", title, "Удалить", lambda: self.app.mutate("Удалено", action)
        )

    def _teachers_table(self):
        subjects = {s["id"]: s["name"] for s in self.repo.subjects()}
        rows = []
        for t in self.repo.teachers():
            taught = ", ".join(sorted(subjects[s] for s in self.repo.teacher_subject_ids(t["id"])))
            slots = {s["id"]: s["number"] for s in self.repo.slots()}
            off = ", ".join(f"{DAY_SHORT[d]} {slots[s]}" for d, s in sorted(self.repo.teacher_off(t["id"])))
            rows.append({"id": t["id"], "cells": [t["full_name"], taught, off]})
        return ["ФИО", "Предметы", ("Не может вести", "День и номер урока, когда учитель не может вести уроки")], rows

    def _teachers_form(self, key):
        t = next((x for x in self.repo.teachers() if x["id"] == key), None)
        days = [(d["id"], DAY_SHORT[d["id"]]) for d in self.repo.weekdays()]
        slots = [(s["id"], str(s["number"])) for s in self.repo.slots(1)]
        fields = [
            {"key": "last", "label": "Фамилия", "required": True, "value": t and t["last_name"]},
            {"key": "first", "label": "Имя", "required": True, "value": t and t["first_name"]},
            {"key": "pat", "label": "Отчество", "value": t and t["patronymic"], "hint": "Можно оставить пустым"},
            {
                "key": "subjects", "label": "Какие предметы ведёт", "type": "checks",
                "value": self.repo.teacher_subject_ids(key) if key else (),
                "items": [(s["id"], s["name"]) for s in self.repo.subjects()],
            },
            {
                "key": "off", "label": "Когда не может вести уроки (строки — номера уроков)", "type": "grid",
                "value": self.repo.teacher_off(key) if key else (), "cols": days, "rows": slots,
            },
        ]
        FormDialog(
            self.app, "Изменить учителя" if key else "Добавить учителя", fields, None,
            lambda v: self.app.mutate(
                "Сохранено",
                lambda: self.repo.save_teacher(key, v["last"], v["first"], v["pat"], v["subjects"], v["off"]),
            ),
        )

    def _teachers_delete(self, key):
        if self.repo.teacher_in_use(key):
            info_dialog(self.app, "Удалить пока нельзя", "У этого учителя есть уроки в «Нагрузке». Сначала передайте их другому учителю.")
            return
        name = next(t["full_name"] for t in self.repo.teachers() if t["id"] == key)
        self._ask_delete(name, lambda: self.repo.delete_teacher(key))

    def _classes_table(self):
        shifts = {s["id"]: s["name"] for s in self.repo.shifts()}
        rows = [
            {"id": x["id"], "cells": [x["name"], shifts[x["shift_id"]], x["students_count"], x["study_days"], x["teacher_short"], x["room_number"]]}
            for x in self.repo.classes()
        ]
        return ["Класс", "Смена", "Учеников", "Учебных дней", "Классный руководитель", "Свой кабинет"], rows

    def _classes_form(self, key):
        x = next((i for i in self.repo.classes() if i["id"] == key), None)
        fields = [
            {"key": "grade", "label": "Параллель", "type": "number", "required": True, "min": 1, "max": 11, "value": x["grade"] if x else 5},
            {"key": "letter", "label": "Буква", "required": True, "value": x and x["letter"]},
            {"key": "shift", "label": "Смена", "type": "select", "value": x["shift_id"] if x else 1, "items": [(s["id"], s["name"]) for s in self.repo.shifts()]},
            {"key": "study", "label": "Учебных дней в неделю", "type": "select", "value": x["study_days"] if x else 5, "items": [(5, "5 дней"), (6, "6 дней")]},
            {"key": "students", "label": "Число учеников", "type": "number", "min": 1, "value": x and x["students_count"], "hint": "Нужно, чтобы проверять, хватает ли мест в кабинете"},
            {"key": "teacher", "label": "Классный руководитель", "type": "select", "empty": "Не выбран", "value": x and x["class_teacher_id"], "items": [(t["id"], t["short"]) for t in self.repo.teachers()]},
            {"key": "room", "label": "Свой кабинет", "type": "select", "empty": "Нет", "value": x and x["home_classroom_id"], "items": [(r["id"], r["number"]) for r in self.repo.rooms()]},
        ]

        def check(v):
            for other in self.repo.classes():
                if other["id"] != key and other["grade"] == v["grade"] and other["letter"] == v["letter"]:
                    return f"Класс {v['grade']}{v['letter']} уже есть"
            return None

        FormDialog(
            self.app, "Изменить класс" if key else "Добавить класс", fields, check,
            lambda v: self.app.mutate(
                "Сохранено",
                lambda: self.repo.save_class(key, v["grade"], v["letter"], v["shift"], v["study"], v["students"], v["teacher"], v["room"]),
            ),
        )

    def _classes_delete(self, key):
        if self.repo.class_in_use(key):
            info_dialog(self.app, "Удалить пока нельзя", "У этого класса есть уроки в «Нагрузке». Сначала удалите их.")
            return
        name = next(x["name"] for x in self.repo.classes() if x["id"] == key)
        self._ask_delete(f"{name} класс", lambda: self.repo.delete_class(key))

    def _subjects_table(self):
        rows = []
        for s in self.repo.subjects():
            scores = format_scores(self.repo.subject_scores(s["id"]))
            rows.append({"id": s["id"], "cells": [s["name"], s["short_name"], s["room_type_name"] or "Любой", scores]})
        hint = "Класс и балл сложности. Например, «1–4: 8» значит 8 баллов в 1, 2, 3 и 4 классах"
        return ["Название", "Коротко", "Нужен кабинет", ("Баллы по классам", hint)], rows

    def _subjects_form(self, key):
        s = next((i for i in self.repo.subjects() if i["id"] == key), None)
        fields = [
            {"key": "name", "label": "Название", "required": True, "value": s and s["name"]},
            {"key": "short", "label": "Короткое название", "value": s and s["short_name"], "hint": "Показывается в клетке расписания"},
            {"key": "type", "label": "Какой нужен кабинет", "type": "select", "empty": "Любой", "value": s and s["required_room_type_id"], "items": [(t["id"], t["name"]) for t in self.repo.room_types()]},
            {
                "key": "scores", "label": "Баллы сложности по классам", "type": "numbers", "min": 1,
                "value": self.repo.subject_scores(key) if key else {}, "items": [(g, f"{g} кл.") for g in range(1, 12)],
                "hint": "Оставьте клетку пустой, если в этом классе предмета нет.",
            },
        ]

        def check(v):
            if any(o["id"] != key and o["name"] == v["name"] for o in self.repo.subjects()):
                return "Такой предмет уже есть"
            return None

        FormDialog(
            self.app, "Изменить предмет" if key else "Добавить предмет", fields, check,
            lambda v: self.app.mutate("Сохранено", lambda: self.repo.save_subject(key, v["name"], v["short"], v["type"], v["scores"])),
        )

    def reset_sanpin(self):
        confirm_dialog(
            self.app, "Вернуть баллы СанПиН?",
            "Для предметов из таблиц СанПиН баллы станут как в таблицах, недостающие предметы добавятся. "
            "Ваши собственные предметы останутся как есть. Вернуть прежние значения можно кнопкой «Отменить».",
            "Вернуть баллы",
            lambda: self.app.mutate("Баллы СанПиН восстановлены", lambda: fill_subjects(self.repo, overwrite=True)),
            icon="undo",
        )

    def _subjects_delete(self, key):
        if self.repo.subject_in_use(key):
            info_dialog(self.app, "Удалить пока нельзя", "Этот предмет есть в «Нагрузке». Сначала удалите его оттуда.")
            return
        name = next(s["name"] for s in self.repo.subjects() if s["id"] == key)
        self._ask_delete(name, lambda: self.repo.delete_subject(key))

    def _rooms_table(self):
        rows = [{"id": r["id"], "cells": [r["number"], r["type_name"], r["capacity"]]} for r in self.repo.rooms()]
        return ["Номер", "Тип", "Мест"], rows

    def _rooms_form(self, key):
        r = next((i for i in self.repo.rooms() if i["id"] == key), None)
        fields = [
            {"key": "number", "label": "Номер или название", "required": True, "value": r and r["number"]},
            {"key": "type", "label": "Тип", "type": "select", "value": r["room_type_id"] if r else 1, "items": [(t["id"], t["name"]) for t in self.repo.room_types()]},
            {"key": "capacity", "label": "Сколько мест", "type": "number", "min": 1, "value": r and r["capacity"]},
        ]

        def check(v):
            if any(o["id"] != key and o["number"] == v["number"] for o in self.repo.rooms()):
                return "Такой кабинет уже есть"
            return None

        FormDialog(
            self.app, "Изменить кабинет" if key else "Добавить кабинет", fields, check,
            lambda v: self.app.mutate("Сохранено", lambda: self.repo.save_room(key, v["number"], v["capacity"], v["type"])),
        )

    def _rooms_delete(self, key):
        number = next(r["number"] for r in self.repo.rooms() if r["id"] == key)
        self._ask_delete(
            f"Кабинет {number}. В расписании у его уроков кабинет станет не назначен.",
            lambda: self.repo.delete_room(key),
        )

    def _slots_table(self):
        shifts = {s["id"]: s["name"] for s in self.repo.shifts()}
        rows = [{"id": s["id"], "cells": [shifts[s["shift_id"]], s["number"], s["starts_at"], s["ends_at"]]} for s in self.repo.slots()]
        return ["Смена", "Номер урока", "Начало", "Конец"], rows

    def _slots_form(self, key):
        s = next((i for i in self.repo.slots() if i["id"] == key), None)
        fields = [
            {"key": "shift", "label": "Смена", "type": "select", "value": s["shift_id"] if s else 1, "items": [(x["id"], x["name"]) for x in self.repo.shifts()]},
            {"key": "number", "label": "Номер урока", "type": "number", "required": True, "min": 1, "value": s["number"] if s else len(self.repo.slots(1)) + 1},
            {"key": "start", "label": "Начало", "type": "time", "value": s and s["starts_at"], "hint": "Например, 08:30"},
            {"key": "end", "label": "Конец", "type": "time", "value": s and s["ends_at"], "hint": "Например, 09:15"},
        ]

        def check(v):
            if any(o["id"] != key and o["shift_id"] == v["shift"] and o["number"] == v["number"] for o in self.repo.slots()):
                return "Такой номер урока в этой смене уже есть"
            if v["start"] and v["end"] and v["start"] >= v["end"]:
                return "Конец урока должен быть позже начала"
            return None

        FormDialog(
            self.app, "Изменить урок" if key else "Добавить урок", fields, check,
            lambda v: self.app.mutate("Сохранено", lambda: self.repo.save_slot(key, v["shift"], v["number"], v["start"], v["end"])),
        )

    def _slots_delete(self, key):
        if self.repo.slot_in_use(key):
            info_dialog(self.app, "Удалить пока нельзя", "На этот номер урока уже поставлены уроки. Сначала уберите их из расписания.")
            return
        slot = next(s for s in self.repo.slots() if s["id"] == key)
        self._ask_delete(f"{slot['number']} урок", lambda: self.repo.delete_slot(key))
