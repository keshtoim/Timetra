import os
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = 1


def default_db_path() -> Path:
    # не рядом с exe: в Program Files обычному пользователю писать нельзя
    return Path(os.environ["LOCALAPPDATA"]) / "Timetra" / "timetra.db"


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        if conn.execute("PRAGMA user_version").fetchone()[0] == 0:
            # одна транзакция: при ошибке не останется полусозданной базы
            schema = SCHEMA_PATH.read_text(encoding="utf-8")
            conn.executescript(f"BEGIN;\n{schema}\nPRAGMA user_version = {SCHEMA_VERSION};\nCOMMIT;")
    except Exception:
        conn.close()
        raise
    return conn
