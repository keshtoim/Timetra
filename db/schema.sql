-- foreign_keys в SQLite действует на соединение, включать при каждом подключении
PRAGMA foreign_keys = ON;

CREATE TABLE subjects (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE CHECK (name <> '')
) STRICT;

-- балл по шкале СанПиН зависит и от предмета, и от параллели
CREATE TABLE subject_difficulty (
    subject_id INTEGER NOT NULL REFERENCES subjects (id) ON DELETE CASCADE,
    grade      INTEGER NOT NULL CHECK (grade BETWEEN 1 AND 11),
    score      INTEGER NOT NULL CHECK (score > 0),
    PRIMARY KEY (subject_id, grade)
) STRICT;

-- без UNIQUE: в школе бывают полные тёзки
CREATE TABLE teachers (
    id         INTEGER PRIMARY KEY,
    last_name  TEXT NOT NULL CHECK (last_name <> ''),
    first_name TEXT NOT NULL CHECK (first_name <> ''),
    patronymic TEXT
) STRICT;

CREATE TABLE classes (
    id     INTEGER PRIMARY KEY,
    grade  INTEGER NOT NULL CHECK (grade BETWEEN 1 AND 11),
    letter TEXT NOT NULL CHECK (letter <> ''),
    UNIQUE (grade, letter)
) STRICT;

CREATE TABLE week_types (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
) STRICT;

INSERT INTO week_types (id, name) VALUES (1, 'Нечётная'), (2, 'Чётная');

-- id совпадает с номером дня по ISO: 1 = понедельник
CREATE TABLE weekdays (
    id   INTEGER PRIMARY KEY CHECK (id BETWEEN 1 AND 7),
    name TEXT NOT NULL UNIQUE
) STRICT;

INSERT INTO weekdays (id, name) VALUES
    (1, 'Понедельник'),
    (2, 'Вторник'),
    (3, 'Среда'),
    (4, 'Четверг'),
    (5, 'Пятница'),
    (6, 'Суббота');

-- subgroup: 0 = весь класс, 1, 2... = подгруппы (NOT NULL, иначе UNIQUE не сработает).
-- Часы за две недели, чтобы без дробей хранить предмет раз в две недели.
CREATE TABLE workload (
    id                    INTEGER PRIMARY KEY,
    class_id              INTEGER NOT NULL REFERENCES classes (id),
    subject_id            INTEGER NOT NULL REFERENCES subjects (id),
    subgroup              INTEGER NOT NULL DEFAULT 0 CHECK (subgroup >= 0),
    teacher_id            INTEGER NOT NULL REFERENCES teachers (id),
    lessons_per_fortnight INTEGER NOT NULL CHECK (lessons_per_fortnight > 0),
    UNIQUE (class_id, subject_id, subgroup)
) STRICT;

-- Итоговое расписание. Урок "каждую неделю" = две строки, по одной на тип недели.
-- Накладки не запрещены на уровне БД: черновик и импорт могут их содержать,
-- их показывает schedule_conflicts.
CREATE TABLE schedule (
    id            INTEGER PRIMARY KEY,
    workload_id   INTEGER NOT NULL REFERENCES workload (id),
    week_type_id  INTEGER NOT NULL REFERENCES week_types (id),
    weekday_id    INTEGER NOT NULL REFERENCES weekdays (id),
    lesson_number INTEGER NOT NULL CHECK (lesson_number >= 1),
    UNIQUE (workload_id, week_type_id, weekday_id, lesson_number)
) STRICT;

CREATE INDEX idx_schedule_slot ON schedule (week_type_id, weekday_id, lesson_number);

-- LEFT JOIN: урок без заполненного балла не должен пропадать из расписания
CREATE VIEW schedule_view AS
SELECT
    s.id AS schedule_id,
    wt.name AS week_type,
    d.name AS weekday,
    s.lesson_number,
    c.grade || c.letter AS class_name,
    w.subgroup,
    subj.name AS subject,
    t.last_name || ' ' || t.first_name || COALESCE(' ' || t.patronymic, '') AS teacher,
    sd.score AS difficulty
FROM schedule s
JOIN workload w ON w.id = s.workload_id
JOIN week_types wt ON wt.id = s.week_type_id
JOIN weekdays d ON d.id = s.weekday_id
JOIN classes c ON c.id = w.class_id
JOIN subjects subj ON subj.id = w.subject_id
JOIN teachers t ON t.id = w.teacher_id
LEFT JOIN subject_difficulty sd ON sd.subject_id = w.subject_id AND sd.grade = c.grade;

-- Разные подгруппы одного класса могут заниматься одновременно,
-- весь класс (subgroup = 0) пересекается с любой подгруппой.
CREATE VIEW schedule_conflicts AS
SELECT 'teacher' AS conflict_type, s1.id AS schedule_id_1, s2.id AS schedule_id_2
FROM schedule s1
JOIN schedule s2
    ON s2.week_type_id = s1.week_type_id
    AND s2.weekday_id = s1.weekday_id
    AND s2.lesson_number = s1.lesson_number
    AND s2.id > s1.id
JOIN workload w1 ON w1.id = s1.workload_id
JOIN workload w2 ON w2.id = s2.workload_id
WHERE w1.teacher_id = w2.teacher_id
UNION ALL
SELECT 'class', s1.id, s2.id
FROM schedule s1
JOIN schedule s2
    ON s2.week_type_id = s1.week_type_id
    AND s2.weekday_id = s1.weekday_id
    AND s2.lesson_number = s1.lesson_number
    AND s2.id > s1.id
JOIN workload w1 ON w1.id = s1.workload_id
JOIN workload w2 ON w2.id = s2.workload_id
WHERE w1.class_id = w2.class_id
    AND (w1.subgroup = w2.subgroup OR w1.subgroup = 0 OR w2.subgroup = 0);

-- Нагрузка класса за день. Параллельные подгруппы — один урок для класса,
-- поэтому сначала берём максимум по слоту, чтобы не считать его дважды.
CREATE VIEW daily_difficulty AS
SELECT week_type_id, weekday_id, class_id, SUM(slot_score) AS total_score
FROM (
    SELECT
        s.week_type_id,
        s.weekday_id,
        w.class_id,
        MAX(COALESCE(sd.score, 0)) AS slot_score
    FROM schedule s
    JOIN workload w ON w.id = s.workload_id
    JOIN classes c ON c.id = w.class_id
    LEFT JOIN subject_difficulty sd ON sd.subject_id = w.subject_id AND sd.grade = c.grade
    GROUP BY s.week_type_id, s.weekday_id, s.lesson_number, w.class_id
)
GROUP BY week_type_id, weekday_id, class_id;
