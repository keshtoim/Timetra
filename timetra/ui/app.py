import sqlite3
import tkinter as tk


class App(tk.Tk):
    def __init__(self, conn: sqlite3.Connection) -> None:
        super().__init__()
        self.conn = conn
        self.title("Timetra")
        self.geometry("1100x700")
        self.minsize(800, 500)
