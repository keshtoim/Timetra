"""Сквозные сценарии через события окна, как при работе мышью, а не прямым вызовом методов."""

import ctypes
import datetime
import threading
import time
import tkinter as tk
import unittest
from ctypes import wintypes
from unittest import mock

from tests.test_schedule_ui import ScheduleCase
from timetra.io.tables import read_table
from timetra.services.substitutions import week_for_date
from timetra.ui.dialogs import Dialog
from timetra.ui.widgets import Btn, Tooltip

MONDAY = datetime.date(2026, 11, 2)
TIP_WAIT_MS = 700
DIALOG_WAIT_S = 15
WM_SETTEXT, BM_CLICK, IDOK = 0x000C, 0x00F5, 1


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


class E2ECase(ScheduleCase):
    def setUp(self):
        super().setUp()
        self.app.settings.week_offset = 0 if week_for_date(MONDAY, 0) == 1 else 1
        self.app.substitutions_state.date = MONDAY
        self.app.geometry("1280x800")
        self.app.deiconify()
        self.app.update()

    def click(self, widget):
        widget.event_generate("<Enter>")
        widget.event_generate("<ButtonPress-1>", x=3, y=3)
        widget.event_generate("<ButtonRelease-1>", x=3, y=3)
        self.app.update()

    def by_text(self, text, root=None):
        for widget in walk(root or self.app):
            if isinstance(widget, tk.Label) and widget.cget("text") == text and widget.winfo_ismapped():
                return widget
        self.fail(f"нет подписи «{text}»")

    def button(self, text, root=None):
        return self.by_text(text, root)

    def wait(self, ms):
        done = tk.BooleanVar(self.app, False)
        self.app.after(ms, lambda: done.set(True))
        self.app.wait_variable(done)

    def drag(self, grid, start, end):
        body = grid.body
        x1, y1 = int(start[0] - body.canvasx(0)), int(start[1] - body.canvasy(0))
        x2, y2 = int(end[0] - body.canvasx(0)), int(end[1] - body.canvasy(0))
        body.event_generate("<ButtonPress-1>", x=x1, y=y1)
        body.event_generate("<B1-Motion>", x=x1 + 10, y=y1 + 10)
        body.event_generate("<B1-Motion>", x=x2, y=y2)
        body.event_generate("<ButtonRelease-1>", x=x2, y=y2)
        self.app.update()

    def center(self, grid, column, row):
        return (column + 0.5) * grid.col_width, grid.row_tops[row] + 5


class NavigationTest(E2ECase):
    def test_every_menu_item_opens_by_click(self):
        for caption, screen in [("Замены", "substitutions"), ("Проверка", "check"), ("Нагрузка", "load"), ("Справочники", "refs"), ("Импорт и экспорт", "exchange"), ("Настройки", "settings"), ("С чего начать", "help"), ("Расписание", "schedule")]:
            self.click(self.by_text(caption, self.app.nav))
            self.assertEqual(self.app.screen, screen)

    def test_collapse_button_and_tab_clicks(self):
        self.click(self.by_text("Свернуть меню", self.app.nav))
        self.assertTrue(self.app.settings.nav_collapsed)
        self.click(self.by_text("Учителя", self.app.content))
        self.assertEqual(self.app.schedule_state.view, "teachers")

    def test_tooltip_appears_on_hover_and_hides_on_leave(self):
        button = next(w for w in walk(self.app.content) if isinstance(w, Btn))
        with mock.patch.object(Tooltip, "_show", autospec=True, side_effect=Tooltip._show) as shown:
            Tooltip(button, "Подсказка")
            button.event_generate("<Enter>")
            self.wait(TIP_WAIT_MS)
            self.assertTrue(shown.called)
            tips = [w for w in walk(button) if w.winfo_class() == "Toplevel"]
            self.assertTrue(tips)
            button.event_generate("<Leave>")
            self.app.update()
            self.assertFalse([w for w in walk(button) if w.winfo_class() == "Toplevel"])

    def test_hover_recolors_button_and_leave_restores(self):
        button = next(w for w in walk(self.app.content) if isinstance(w, Btn) and w.hover_color != w.bg_color)
        button.event_generate("<Enter>")
        self.assertEqual(button.fill_color, button.hover_color)
        button.event_generate("<Leave>")
        self.assertEqual(button.fill_color, button.bg_color)


class ScheduleScenario(E2ECase):
    def setUp(self):
        super().setUp()
        self.screen.place(self.w1, self.col(self.c1), self.slot)
        self.app.schedule_state.view = "classes"
        self.reload()

    def test_drag_lesson_to_other_slot_with_mouse_events(self):
        grid = self.screen.grid_view
        self.drag(grid, self.center(grid, 0, 0), self.center(grid, 0, 2))
        self.assertEqual({r["lesson_slot_id"] for r in self.lessons()}, {self.slots[2]["id"]})

    def test_click_card_opens_dialog_and_save_button_works(self):
        grid = self.screen.grid_view
        x, y = self.center(grid, 0, 0)
        grid.body.event_generate("<ButtonPress-1>", x=int(x), y=int(y))
        grid.body.event_generate("<ButtonRelease-1>", x=int(x), y=int(y))
        self.app.update()
        dialog = next(w for w in self.app.winfo_children() if isinstance(w, Dialog))
        self.click(self.by_text("Сохранить", dialog))
        self.assertFalse(dialog.winfo_exists())
        self.assertEqual(len(self.lessons()), 2)

    def test_drag_from_panel_to_cell(self):
        self.app.schedule_state.both = True
        self.reload()
        row = next(w for w in walk(self.app.content) if isinstance(w, tk.Label) and w.cget("text").startswith("Музыка ×"))
        grid = self.screen.grid_view
        row.event_generate("<ButtonPress-1>", x=3, y=3, rootx=row.winfo_rootx() + 3, rooty=row.winfo_rooty() + 3)
        self.app.update()
        x, y = self.center(grid, 1, 2)
        target_x = int(grid.body.winfo_rootx() + x - grid.body.canvasx(0))
        target_y = int(grid.body.winfo_rooty() + y - grid.body.canvasy(0))
        # winfo_containing смотрит на реальное положение окон, а поверх могут быть чужие окна
        with mock.patch.object(grid, "winfo_containing", return_value=grid.body):
            row.event_generate("<B1-Motion>", x=3, y=3, rootx=target_x, rooty=target_y)
            row.event_generate("<ButtonRelease-1>", x=3, y=3, rootx=target_x, rooty=target_y)
            self.app.update()
        music = [r for r in self.lessons() if r["workload_id"] == self.w3]
        self.assertEqual({r["lesson_slot_id"] for r in music}, {self.slots[2]["id"]})


class DayScenario(E2ECase):
    def setUp(self):
        super().setUp()
        with self.conn:
            self.repo.add_lesson(self.ver, self.w1, 1, 1, self.slot, self.r1)
        self.app.schedule_state.view = "date"
        self.reload()

    def saved(self):
        return self.conn.execute("SELECT * FROM substitutions").fetchall()

    def test_drag_on_date_tab_moves_one_day_only(self):
        grid = self.screen.grid_view
        self.drag(grid, self.center(grid, 0, 0), self.center(grid, 0, 3))
        self.assertEqual(self.saved()[0]["lesson_slot_id"], self.slots[3]["id"])
        self.assertEqual(self.lessons()[0]["lesson_slot_id"], self.slot)

    def test_click_empty_cell_adds_extra_through_dialog(self):
        grid = self.screen.grid_view
        x, y = self.center(grid, 1, 4)
        grid.body.event_generate("<ButtonPress-1>", x=int(x), y=int(y))
        grid.body.event_generate("<ButtonRelease-1>", x=int(x), y=int(y))
        self.app.update()
        dialog = next(w for w in self.app.winfo_children() if isinstance(w, Dialog))
        self.click(self.by_text("Сохранить", dialog))
        row = self.conn.execute("SELECT * FROM extra_lessons").fetchone()
        self.assertEqual((row["class_id"], row["lesson_slot_id"]), (self.c2, self.slots[4]["id"]))

    def test_date_buttons_change_day(self):
        self.click(self.by_text("Вперёд", self.app.content))
        self.assertEqual(self.app.substitutions_state.date, MONDAY + datetime.timedelta(days=1))
        self.click(self.by_text("Назад", self.app.content))
        self.assertEqual(self.app.substitutions_state.date, MONDAY)


def _press_save_in_native_dialog(title, target, errors):
    """Настоящее окно Windows: находим по заголовку и управляем сообщениями, не трогая мышь и клавиатуру."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPCWSTR]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.GetDlgItem.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetDlgItem.restype = wintypes.HWND
    deadline = time.monotonic() + DIALOG_WAIT_S
    while time.monotonic() < deadline:
        window = user32.FindWindowW("#32770", title)
        if window:
            break
        time.sleep(0.1)
    else:
        errors.append("окно сохранения не появилось")
        return
    edits = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def collect(hwnd, _param):
        name = ctypes.create_unicode_buffer(32)
        user32.GetClassNameW(hwnd, name, 32)
        if name.value == "Edit" and user32.IsWindowVisible(hwnd):
            edits.append(hwnd)
        return True

    # заголовок появляется раньше полей, под нагрузкой они создаются заметно позже
    while not edits and time.monotonic() < deadline:
        time.sleep(0.1)
        user32.EnumChildWindows(window, callback_type(collect), 0)
    if not edits:
        errors.append("нет поля имени файла")
        return
    time.sleep(0.3)
    user32.SendMessageW(edits[0], WM_SETTEXT, 0, str(target))
    user32.SendMessageW(user32.GetDlgItem(window, IDOK), BM_CLICK, 0, None)


class NativeSaveDialogTest(E2ECase):
    def run_with_dialog(self, button_text, title, target):
        errors = []
        thread = threading.Thread(target=_press_save_in_native_dialog, args=(title, target, errors), daemon=True)
        thread.start()
        self.click(self.by_text(button_text, self.app.content))
        thread.join(DIALOG_WAIT_S + 2)
        self.assertEqual(errors, [])
        self.app.update()
        self.assertTrue(target.exists(), target)

    def test_substitutions_file(self):
        self.screen.place(self.w1, self.col(self.c1), self.slot)
        lesson = next(r for r in self.lessons() if r["week_type_id"] == 1)
        with self.conn:
            self.repo.save_substitution(lesson["id"], MONDAY.isoformat(), self.t2, None, None, False, "болеет")
        self.app.go("substitutions")
        self.app.update()
        target = self.tmp / "замены.xlsx"
        self.run_with_dialog("Сохранить замены в файл", "Куда сохранить замены", target)
        self.assertEqual(read_table(target)[1][-1], "болеет")

    def test_school_grid_export(self):
        self.app.go("exchange")
        self.app.update()
        target = self.tmp / "сетка.xlsx"
        self.run_with_dialog("Сохранить файл", "Куда сохранить файл", target)

    def test_backup(self):
        self.app.go("settings")
        self.app.update()
        target = self.tmp / "копия.db"
        self.run_with_dialog("Сделать копию базы", "Куда сохранить копию", target)


if __name__ == "__main__":
    unittest.main()
