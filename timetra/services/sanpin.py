from timetra.db.repo import Repo

# Шкала трудности: СанПиН 1.2.3685-21, таблицы 6.9 (1-4 классы), 6.10 (5-9), 6.11 (10-11).
# Значения: (короткое название, тип кабинета, балл 1-4, баллы 5-9, балл 10-11); None — предмета нет в таблице.
# "Русский язык/Родной язык" в таблицах одна строка, в школе это два предмета с разной нагрузкой.
SUBJECTS = {
    "Математика": ("Матем.", None, 8, (10, 13, None, None, None), None),
    "Алгебра": ("Алгебра", None, None, (None, None, 10, 9, 7), 10),
    "Геометрия": ("Геом.", None, None, (None, None, 12, 10, 8), 11),
    "Русский язык": ("Русский", None, 7, (8, 12, 11, 7, 6), 9),
    "Родной язык": ("Родной", None, 7, (8, 12, 11, 7, 6), 9),
    "Литературное чтение": ("Лит. чт.", None, 5, (None,) * 5, None),
    "Литература": ("Литер.", None, None, (4, 6, 4, 4, 7), 8),
    "Иностранный язык": ("Ин. яз.", None, 7, (9, 11, 10, 8, 9), 8),
    "Информатика и ИКТ": ("Информ.", "Компьютерный класс", 6, (4, 10, 4, 7, 7), 6),
    "Окружающий мир": ("Окр. мир", None, 6, (None,) * 5, None),
    "Природоведение": ("Природов.", None, None, (7, 8, None, None, None), None),
    "Биология": ("Биол.", None, None, (10, 8, 7, 7, 7), 7),
    "География": ("Геогр.", None, None, (None, 7, 6, 6, 5), 3),
    "Физика": ("Физика", None, None, (None, None, 8, 9, 13), 12),
    "Химия": ("Химия", None, None, (None, None, None, 10, 12), 11),
    "История": ("История", None, None, (5, 8, 6, 8, 10), 5),
    "Обществознание": ("Общ.", None, None, (6, 9, 9, 5, 5), 5),
    "Мировая художественная культура": ("МХК", None, None, (None, None, 8, 5, 5), 5),
    "Изобразительное искусство": ("ИЗО", None, 3, (3, 3, 1, None, None), None),
    "Музыка": ("Музыка", None, 3, (2, 1, 1, 1, None), None),
    "Технология": ("Технол.", None, 2, (4, 3, 2, 1, 4), None),
    "Черчение": ("Черч.", None, None, (None, None, None, 5, 4), None),
    "Основы безопасности жизнедеятельности": ("ОБЖ", None, None, (1, 2, 3, 3, 3), 2),
    "Физическая культура": ("Физра", "Спортзал", 1, (3, 4, 2, 2, 2), 1),
}

# user_version после первичного заполнения: чтобы удалённые школой предметы не возвращались при запуске
SEEDED_VERSION = 2


def sanpin_scores(subject: str) -> dict[int, int]:
    _short, _room, primary, middle, senior = SUBJECTS[subject]
    scores = {grade: primary for grade in range(1, 5)}
    scores.update(zip(range(5, 10), middle))
    scores.update({10: senior, 11: senior})
    return {grade: score for grade, score in scores.items() if score}


def fill_subjects(repo: Repo, overwrite: bool = False) -> int:
    """Добавляет предметы из таблиц и дописывает пустые баллы, с overwrite возвращает значения СанПиН.

    Транзакцию открывает вызывающий код. Возвращает число добавленных предметов.
    """
    existing = {s["name"]: s for s in repo.subjects()}
    room_types = {t["name"]: t["id"] for t in repo.room_types()}
    added = 0
    for name, (short, room, *_rest) in SUBJECTS.items():
        table = sanpin_scores(name)
        current = existing.get(name)
        if current is None:
            repo.save_subject(None, name, short, room_types[room] if room else None, table)
            added += 1
            continue
        own = repo.subject_scores(current["id"])
        scores = {**own, **table} if overwrite else {**table, **own}
        repo.save_subject(current["id"], name, current["short_name"], current["required_room_type_id"], scores)
    return added


def seed_once(repo: Repo) -> None:
    conn = repo.conn
    if conn.execute("PRAGMA user_version").fetchone()[0] >= SEEDED_VERSION:
        return
    with conn:
        fill_subjects(repo)
        conn.execute(f"PRAGMA user_version = {SEEDED_VERSION}")


def format_scores(scores: dict[int, int]) -> str:
    """Подряд идущие классы с одним баллом склеиваются: {1: 8, 2: 8, 3: 8, 5: 10} -> "1–3: 8; 5: 10"."""
    parts = []
    grades = sorted(scores)
    start = 0
    for i, grade in enumerate(grades):
        is_last = i + 1 == len(grades)
        if is_last or grades[i + 1] != grade + 1 or scores[grades[i + 1]] != scores[grade]:
            first = grades[start]
            label = str(first) if first == grade else f"{first}–{grade}"
            parts.append(f"{label}: {scores[grade]}")
            start = i + 1
    return "; ".join(parts)
