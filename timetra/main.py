import ctypes

from timetra.db.connection import connect, default_db_path
from timetra.db.repo import Repo
from timetra.services.sanpin import seed_once
from timetra.ui.app import App


def main() -> None:
    # иначе Windows растягивает окно картинкой и текст получается мутным
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    db_path = default_db_path()
    conn = connect(db_path)
    try:
        seed_once(Repo(conn))
        App(conn, db_path.with_name("settings.json")).mainloop()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
