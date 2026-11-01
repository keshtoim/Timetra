import tempfile
import unittest
from pathlib import Path

from timetra.db.connection import connect
from timetra.ui.app import SCREENS, App


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


if __name__ == "__main__":
    unittest.main()
