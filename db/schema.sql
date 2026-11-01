-- foreign_keys в SQLite действует на соединение, включать при каждом подключении
PRAGMA foreign_keys = ON;

CREATE TABLE room_types (                     -- типы кабинетов
    id   INTEGER PRIMARY KEY,                 -- идентификатор типа
    name TEXT NOT NULL UNIQUE CHECK (name <> '') -- название типа: обычный, спортзал...
) STRICT;

INSERT INTO room_types (name) VALUES ('Обычный');

CREATE TABLE classrooms (                     -- кабинеты школы
    id           INTEGER PRIMARY KEY,         -- идентификатор кабинета
    number       TEXT NOT NULL UNIQUE CHECK (number <> ''), -- номер кабинета, текст: бывает "12а"
    capacity     INTEGER CHECK (capacity > 0), -- вместимость, пусто = не указана
    room_type_id INTEGER NOT NULL REFERENCES room_types (id) -- тип кабинета
) STRICT;

CREATE TABLE shifts (                         -- учебные смены
    id   INTEGER PRIMARY KEY,                 -- идентификатор смены
    name TEXT NOT NULL UNIQUE CHECK (name <> '') -- название смены
) STRICT;

INSERT INTO shifts (id, name) VALUES (1, 'Первая'), (2, 'Вторая');

CREATE TABLE lesson_slots (                   -- номера уроков и звонки по сменам
    id        INTEGER PRIMARY KEY,            -- идентификатор слота
    shift_id  INTEGER NOT NULL REFERENCES shifts (id), -- смена
    number    INTEGER NOT NULL CHECK (number >= 1), -- номер урока в смене
    starts_at TEXT CHECK (starts_at GLOB '[0-2][0-9]:[0-5][0-9]'), -- начало, ЧЧ:ММ, пусто = не задано
    ends_at   TEXT CHECK (ends_at GLOB '[0-2][0-9]:[0-5][0-9]'), -- конец, ЧЧ:ММ, пусто = не задано
    UNIQUE (shift_id, number),                -- номер урока не повторяется в смене
    CHECK (starts_at < ends_at)               -- урок заканчивается позже начала
) STRICT;

CREATE TABLE grades (                         -- параллели
    number            INTEGER PRIMARY KEY CHECK (number BETWEEN 1 AND 11), -- номер параллели
    max_daily_lessons INTEGER CHECK (max_daily_lessons > 0) -- лимит уроков в день, пусто = не задан
) STRICT;

INSERT INTO grades (number) VALUES (1), (2), (3), (4), (5), (6), (7), (8), (9), (10), (11);

CREATE TABLE grade_load_limits (              -- недельные лимиты СанПиН
    grade            INTEGER NOT NULL REFERENCES grades (number) ON DELETE CASCADE, -- параллель
    study_days       INTEGER NOT NULL CHECK (study_days IN (5, 6)), -- длина учебной недели, дней
    max_weekly_hours INTEGER NOT NULL CHECK (max_weekly_hours > 0), -- максимум часов в неделю
    PRIMARY KEY (grade, study_days)           -- лимит зависит от параллели и длины недели
) STRICT;

CREATE TABLE teachers (                       -- учителя; без UNIQUE: бывают полные тёзки
    id         INTEGER PRIMARY KEY,           -- идентификатор учителя
    last_name  TEXT NOT NULL CHECK (last_name <> ''), -- фамилия
    first_name TEXT NOT NULL CHECK (first_name <> ''), -- имя
    patronymic TEXT                           -- отчество, может отсутствовать
) STRICT;

CREATE TABLE classes (                        -- классы
    id                INTEGER PRIMARY KEY,    -- идентификатор класса
    grade             INTEGER NOT NULL REFERENCES grades (number), -- параллель
    letter            TEXT NOT NULL CHECK (letter <> ''), -- буква класса
    shift_id          INTEGER NOT NULL REFERENCES shifts (id), -- смена класса
    study_days        INTEGER NOT NULL DEFAULT 5 CHECK (study_days IN (5, 6)), -- пяти- или шестидневка
    students_count    INTEGER CHECK (students_count > 0), -- число учеников, пусто = не указано
    class_teacher_id  INTEGER REFERENCES teachers (id) ON DELETE SET NULL, -- классный руководитель
    home_classroom_id INTEGER REFERENCES classrooms (id) ON DELETE SET NULL, -- закреплённый кабинет
    UNIQUE (grade, letter)                    -- класс не повторяется в параллели
) STRICT;

CREATE TABLE subjects (                       -- предметы (уроки)
    id                    INTEGER PRIMARY KEY, -- идентификатор предмета
    name                  TEXT NOT NULL UNIQUE CHECK (name <> ''), -- полное название
    short_name            TEXT,               -- короткое название для сетки расписания
    required_room_type_id INTEGER REFERENCES room_types (id) ON DELETE SET NULL -- нужный тип кабинета, пусто = любой
) STRICT;

CREATE TABLE subject_difficulty (             -- баллы сложности по шкале СанПиН
    subject_id INTEGER NOT NULL REFERENCES subjects (id) ON DELETE CASCADE, -- предмет
    grade      INTEGER NOT NULL REFERENCES grades (number) ON DELETE CASCADE, -- параллель
    score      INTEGER NOT NULL CHECK (score > 0), -- балл сложности
    PRIMARY KEY (subject_id, grade)           -- балл зависит и от предмета, и от параллели
) STRICT;

CREATE TABLE teacher_subjects (               -- какие предметы может вести учитель
    teacher_id INTEGER NOT NULL REFERENCES teachers (id) ON DELETE CASCADE, -- учитель
    subject_id INTEGER NOT NULL REFERENCES subjects (id) ON DELETE CASCADE, -- предмет
    PRIMARY KEY (teacher_id, subject_id)      -- пара не повторяется
) STRICT;

CREATE TABLE week_types (                     -- типы недель
    id   INTEGER PRIMARY KEY,                 -- идентификатор типа недели
    name TEXT NOT NULL UNIQUE                 -- название: чётная или нечётная
) STRICT;

INSERT INTO week_types (id, name) VALUES (1, 'Нечётная'), (2, 'Чётная');

CREATE TABLE weekdays (                       -- дни недели
    id   INTEGER PRIMARY KEY CHECK (id BETWEEN 1 AND 7), -- номер дня по ISO: 1 = понедельник
    name TEXT NOT NULL UNIQUE                 -- название дня
) STRICT;

INSERT INTO weekdays (id, name) VALUES
    (1, 'Понедельник'),
    (2, 'Вторник'),
    (3, 'Среда'),
    (4, 'Четверг'),
    (5, 'Пятница'),
    (6, 'Суббота');

CREATE TABLE teacher_unavailability (         -- когда учитель не может вести уроки
    teacher_id     INTEGER NOT NULL REFERENCES teachers (id) ON DELETE CASCADE, -- учитель
    weekday_id     INTEGER NOT NULL REFERENCES weekdays (id), -- день недели
    lesson_slot_id INTEGER NOT NULL REFERENCES lesson_slots (id) ON DELETE CASCADE, -- номер урока
    PRIMARY KEY (teacher_id, weekday_id, lesson_slot_id) -- запись не повторяется
) STRICT;

CREATE TABLE workload (                       -- нагрузка: кто что ведёт в каком классе
    id                    INTEGER PRIMARY KEY, -- идентификатор нагрузки
    class_id              INTEGER NOT NULL REFERENCES classes (id), -- класс
    subject_id            INTEGER NOT NULL REFERENCES subjects (id), -- предмет
    subgroup              INTEGER NOT NULL DEFAULT 0 CHECK (subgroup >= 0), -- 0 = весь класс, 1, 2... = подгруппы; NOT NULL, иначе UNIQUE не сработает
    teacher_id            INTEGER NOT NULL REFERENCES teachers (id), -- учитель
    lessons_per_fortnight INTEGER NOT NULL CHECK (lessons_per_fortnight > 0), -- уроков за две недели: без дробей для предмета раз в две недели
    UNIQUE (class_id, subject_id, subgroup)   -- у подгруппы по предмету один учитель
) STRICT;

CREATE TABLE schedule_versions (              -- варианты расписания: черновик, четверть...
    id         INTEGER PRIMARY KEY,           -- идентификатор варианта
    name       TEXT NOT NULL UNIQUE CHECK (name <> ''), -- название варианта
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, -- дата создания, UTC
    is_active  INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0, 1)) -- 1 = действующий вариант
) STRICT;

-- действующим может быть только один вариант
CREATE UNIQUE INDEX idx_schedule_versions_active ON schedule_versions (is_active) WHERE is_active = 1;

-- Итоговое расписание. Урок "каждую неделю" = две строки, по одной на тип недели.
-- Накладки не запрещены на уровне БД: черновик и импорт могут их содержать,
-- их показывает schedule_conflicts.
CREATE TABLE schedule (                       -- уроки, поставленные в расписание
    id             INTEGER PRIMARY KEY,       -- идентификатор записи
    version_id     INTEGER NOT NULL REFERENCES schedule_versions (id) ON DELETE CASCADE, -- вариант расписания
    workload_id    INTEGER NOT NULL REFERENCES workload (id), -- нагрузка: класс, предмет, учитель
    week_type_id   INTEGER NOT NULL REFERENCES week_types (id), -- тип недели
    weekday_id     INTEGER NOT NULL REFERENCES weekdays (id), -- день недели
    lesson_slot_id INTEGER NOT NULL REFERENCES lesson_slots (id), -- номер урока
    classroom_id   INTEGER REFERENCES classrooms (id) ON DELETE SET NULL, -- кабинет, пусто = ещё не назначен
    UNIQUE (version_id, workload_id, week_type_id, weekday_id, lesson_slot_id) -- один урок не ставится дважды
) STRICT;

CREATE INDEX idx_schedule_slot ON schedule (version_id, week_type_id, weekday_id, lesson_slot_id);

-- LEFT JOIN: урок без балла или кабинета не должен пропадать из расписания
CREATE VIEW schedule_view AS
SELECT
    s.id AS schedule_id,
    s.version_id,
    wt.name AS week_type,
    d.name AS weekday,
    ls.number AS lesson_number,
    ls.starts_at,
    ls.ends_at,
    c.grade || c.letter AS class_name,
    w.subgroup,
    subj.name AS subject,
    t.last_name || ' ' || t.first_name || COALESCE(' ' || t.patronymic, '') AS teacher,
    r.number AS classroom,
    sd.score AS difficulty
FROM schedule s
JOIN workload w ON w.id = s.workload_id
JOIN week_types wt ON wt.id = s.week_type_id
JOIN weekdays d ON d.id = s.weekday_id
JOIN lesson_slots ls ON ls.id = s.lesson_slot_id
JOIN classes c ON c.id = w.class_id
JOIN subjects subj ON subj.id = w.subject_id
JOIN teachers t ON t.id = w.teacher_id
LEFT JOIN classrooms r ON r.id = s.classroom_id
LEFT JOIN subject_difficulty sd ON sd.subject_id = w.subject_id AND sd.grade = c.grade;

-- Пары уроков, идущих одновременно. Уроки разных смен сравниваем по времени:
-- 6-й урок первой смены может совпасть с 1-м уроком второй.
CREATE VIEW simultaneous_lessons AS
SELECT
    s1.version_id,
    s1.id AS schedule_id_1,
    s2.id AS schedule_id_2,
    s1.workload_id AS workload_id_1,
    s2.workload_id AS workload_id_2,
    s1.classroom_id AS classroom_id_1,
    s2.classroom_id AS classroom_id_2
FROM schedule s1
JOIN schedule s2
    ON s2.version_id = s1.version_id
    AND s2.week_type_id = s1.week_type_id
    AND s2.weekday_id = s1.weekday_id
    AND s2.id > s1.id
JOIN lesson_slots ls1 ON ls1.id = s1.lesson_slot_id
JOIN lesson_slots ls2 ON ls2.id = s2.lesson_slot_id
WHERE ls1.id = ls2.id
    OR (ls1.starts_at < ls2.ends_at AND ls2.starts_at < ls1.ends_at);

-- Разные подгруппы одного класса могут заниматься одновременно,
-- весь класс (subgroup = 0) пересекается с любой подгруппой.
CREATE VIEW schedule_conflicts AS
SELECT 'teacher' AS conflict_type, sl.version_id, sl.schedule_id_1, sl.schedule_id_2
FROM simultaneous_lessons sl
JOIN workload w1 ON w1.id = sl.workload_id_1
JOIN workload w2 ON w2.id = sl.workload_id_2
WHERE w1.teacher_id = w2.teacher_id
UNION ALL
SELECT 'class', sl.version_id, sl.schedule_id_1, sl.schedule_id_2
FROM simultaneous_lessons sl
JOIN workload w1 ON w1.id = sl.workload_id_1
JOIN workload w2 ON w2.id = sl.workload_id_2
WHERE w1.class_id = w2.class_id
    AND (w1.subgroup = w2.subgroup OR w1.subgroup = 0 OR w2.subgroup = 0)
UNION ALL
SELECT 'classroom', sl.version_id, sl.schedule_id_1, sl.schedule_id_2
FROM simultaneous_lessons sl
WHERE sl.classroom_id_1 = sl.classroom_id_2;

-- Нагрузка класса за день. Параллельные подгруппы — один урок для класса,
-- поэтому сначала берём максимум по слоту, чтобы не считать его дважды.
CREATE VIEW daily_difficulty AS
SELECT version_id, week_type_id, weekday_id, class_id, SUM(slot_score) AS total_score
FROM (
    SELECT
        s.version_id,
        s.week_type_id,
        s.weekday_id,
        w.class_id,
        MAX(COALESCE(sd.score, 0)) AS slot_score
    FROM schedule s
    JOIN workload w ON w.id = s.workload_id
    JOIN classes c ON c.id = w.class_id
    LEFT JOIN subject_difficulty sd ON sd.subject_id = w.subject_id AND sd.grade = c.grade
    GROUP BY s.version_id, s.week_type_id, s.weekday_id, s.lesson_slot_id, w.class_id
)
GROUP BY version_id, week_type_id, weekday_id, class_id;
