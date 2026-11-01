import tempfile
import unittest
from pathlib import Path

from timetra.db.connection import connect


class ConnectionTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "nested" / "timetra.db"

    def test_creates_schema_with_foreign_keys_on(self):
        conn = connect(self.path)
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM weekdays").fetchone()[0], 6)

    def test_reopening_keeps_data(self):
        conn = connect(self.path)
        conn.execute("INSERT INTO subjects (name) VALUES ('Математика')")
        conn.commit()
        conn.close()

        conn = connect(self.path)
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM subjects").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
