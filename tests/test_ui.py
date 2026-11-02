import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from timetra.db.connection import connect
from timetra.settings import load_settings
from timetra.ui.app import NAV_COLLAPSED_WIDTH, NAV_WIDTH, SCREENS, App
from timetra.ui.dialogs import FormDialog
from timetra.ui.widgets import RADIUS, Btn, _corner_image


class UiCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.conn = connect(self.tmp / "t.db")
        self.addCleanup(self.conn.close)
        self.app = App(self.conn, self.tmp / "settings.json")
        self.addCleanup(self.app.destroy)
        self.app.update()


class ShellTest(UiCase):
    def test_all_screens_open(self):
        for key, *_rest in SCREENS:
            self.app.go(key)
            self.app.update()
            self.assertEqual(self.app.screen, key)

    def test_theme_change_saved_and_rebuilt(self):
        self.app.settings.theme = "dark"
        self.app.settings_changed()
        self.app.update()
        self.assertEqual(self.app.cget("bg"), "#16211E")
        self.assertIn("dark", (self.tmp / "settings.json").read_text(encoding="utf-8"))

    def test_mutate_and_undo(self):
        self.assertTrue(self.app.mutate("ok", lambda: self.app.repo.save_teacher(None, "Ф", "И", "")))
        self.assertEqual(len(self.app.repo.teachers()), 1)
        self.app.undo()
        self.assertEqual(self.app.repo.teachers(), [])

    def test_mutate_integrity_error_keeps_data_and_no_undo(self):
        self.app.repo.save_room(None, "101", 30, 1)
        self.conn.commit()
        self.assertFalse(self.app.mutate("x", lambda: self.app.repo.save_room(None, "101", 30, 1)))
        self.assertEqual(len(self.app.repo.rooms()), 1)
        self.assertEqual(self.app.undo_stack, [])


class NavTest(UiCase):
    def texts(self):
        return [w.cget("text") for row in self.app.nav.winfo_children() for w in [row, *row.winfo_children()] if isinstance(w, tk.Label)]

    def test_collapse_hides_captions_and_keeps_navigation(self):
        self.assertIn("Нагрузка", self.texts())
        self.app.toggle_nav()
        self.app.update()
        self.assertNotIn("Нагрузка", self.texts())
        self.assertEqual(self.app.nav.winfo_width(), NAV_COLLAPSED_WIDTH)
        self.app.go("load")
        self.app.update()
        self.assertEqual(self.app.screen, "load")
        self.assertNotIn("Нагрузка", self.texts())

    def test_expand_restores_captions(self):
        self.app.toggle_nav()
        self.app.toggle_nav()
        self.app.update()
        self.assertIn("Нагрузка", self.texts())
        self.assertEqual(self.app.nav.winfo_width(), NAV_WIDTH)

    def test_state_remembered_after_restart(self):
        self.app.toggle_nav()
        self.assertTrue(load_settings(self.tmp / "settings.json").nav_collapsed)

    def test_survives_theme_change(self):
        self.app.toggle_nav()
        self.app.settings.theme = "dark"
        self.app.settings_changed()
        self.app.update()
        self.assertEqual(self.app.nav.winfo_width(), NAV_COLLAPSED_WIDTH)


class RoundButtonTest(UiCase):
    def test_button_draws_corners_and_clicks(self):
        clicks = []
        button = Btn(self.app.content, "Тест", "add", lambda: clicks.append(1))
        button.pack()
        self.app.update()
        self.assertEqual(len(button.find_all()) >= 10, True)
        self.assertGreater(button.winfo_height(), RADIUS * 2)
        button.event_generate("<Return>")
        button._click()
        self.assertTrue(clicks)

    def test_hover_recolors_and_disabled_does_nothing(self):
        clicks = []
        button = Btn(self.app.content, "Тест", None, lambda: clicks.append(1), disabled=True)
        button.pack()
        button.paint("#123456")
        self.assertEqual(button.fill_color, "#123456")
        button._click()
        self.assertEqual(clicks, [])

    def test_corner_blends_from_outside_to_fill(self):
        button = Btn(self.app.content, "Тест")
        image = _corner_image(button, False, False, "#ffffff", "#ffffff", "#000000")
        self.assertEqual(image.get(0, 0), (0, 0, 0))
        self.assertEqual(image.get(RADIUS - 1, RADIUS - 1), (255, 255, 255))
        self.assertIs(image, _corner_image(button, False, False, "#ffffff", "#ffffff", "#000000"))


class RefsTest(UiCase):
    def open_form(self, tab, key=None):
        from timetra.ui.refs_screen import RefsScreen

        RefsScreen.tab = tab
        self.app.go("refs")
        self.app.update()
        self.app.current_screen.edit(key)
        self.app.update()
        return next(w for w in self.app.winfo_children() if isinstance(w, FormDialog))

    def fill(self, form, **values):
        for key, value in values.items():
            widget = form.inputs[key]
            widget.delete(0, "end")
            widget.insert(0, value)

    def test_tabs_render_with_data(self):
        from timetra.ui.refs_screen import TABS, RefsScreen

        repo = self.app.repo
        teacher = repo.save_teacher(None, "Иванова", "Мария", "")
        repo.save_subject(None, "Математика", "", None, {5: 10})
        repo.save_room(None, "101", 30, 1)
        repo.save_class(None, 5, "А", 1, 5, 26, teacher, repo.rooms()[0]["id"])
        self.conn.commit()
        for key, *_rest in TABS:
            RefsScreen.tab = key
            self.app.go("refs")
            self.app.update()

    def test_add_room_through_form(self):
        form = self.open_form("rooms")
        self.fill(form, number="301", capacity="20")
        form.submit()
        self.app.update()
        self.assertEqual(self.app.repo.rooms()[0]["number"], "301")

    def test_form_shows_error_and_stays_open(self):
        form = self.open_form("rooms")
        form.submit()
        self.app.update()
        self.assertIn("Номер", form.error.cget("text"))
        self.assertTrue(form.winfo_exists())
        form.destroy()

    def test_slot_time_validated(self):
        form = self.open_form("slots")
        self.fill(form, start="25:00")
        form.submit()
        self.assertIn("время", form.error.cget("text"))
        form.destroy()

    def test_teacher_with_workload_not_deleted(self):
        from timetra.ui.refs_screen import RefsScreen

        repo = self.app.repo
        teacher = repo.save_teacher(None, "Иванова", "Мария", "")
        subject = repo.save_subject(None, "Математика", "", None, {})
        repo.save_class(None, 5, "А", 1, 5, None, None, None)
        repo.save_workload(None, repo.classes()[0]["id"], subject, 0, teacher, 2)
        self.conn.commit()
        RefsScreen.tab = "teachers"
        self.app.go("refs")
        self.app.current_screen.delete(teacher)
        self.app.update()
        self.assertEqual(len(repo.teachers()), 1)


class LoadTest(UiCase):
    def test_add_workload_and_badge(self):
        repo = self.app.repo
        teacher = repo.save_teacher(None, "Иванова", "Мария", "")
        repo.save_subject(None, "Математика", "", None, {})
        repo.save_class(None, 5, "А", 1, 5, None, None, None)
        self.conn.commit()
        self.app.go("load")
        self.app.update()
        self.app.current_screen.edit(None)
        form = next(w for w in self.app.winfo_children() if isinstance(w, FormDialog))
        form.submit()
        self.app.update()
        self.assertEqual(repo.workload(self.app.version_id)[0]["teacher_id"], teacher)

    def test_empty_refs_explained(self):
        self.app.go("load")
        self.app.current_screen.edit(None)
        self.app.update()
        self.assertEqual(self.app.repo.workload(self.app.version_id), [])


if __name__ == "__main__":
    unittest.main()
