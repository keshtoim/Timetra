from timetra.db.connection import connect, default_db_path
from timetra.ui.app import App


def main() -> None:
    conn = connect(default_db_path())
    try:
        App(conn).mainloop()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
