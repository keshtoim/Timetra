-- Отдельный файл по той же причине, что substitutions.sql: уже созданные базы получают это при запуске
ALTER TABLE substitutions ADD COLUMN lesson_slot_id INTEGER REFERENCES lesson_slots (id); -- на какой урок перенесён в этот день, пусто = без переноса

CREATE TABLE extra_lessons (                  -- дополнительный урок на дату, которого нет в расписании
    id             INTEGER PRIMARY KEY,       -- идентификатор урока
    version_id     INTEGER NOT NULL REFERENCES schedule_versions (id) ON DELETE CASCADE, -- вариант расписания
    lesson_date    TEXT NOT NULL CHECK (lesson_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'), -- дата, ГГГГ-ММ-ДД
    week_type_id   INTEGER NOT NULL REFERENCES week_types (id), -- тип недели этой даты: триггеру нужно сравнить с расписанием
    lesson_slot_id INTEGER NOT NULL REFERENCES lesson_slots (id), -- номер урока
    class_id       INTEGER NOT NULL REFERENCES classes (id), -- класс
    subgroup       INTEGER NOT NULL DEFAULT 0 CHECK (subgroup >= 0), -- 0 = весь класс, 1, 2... = подгруппы
    subject_id     INTEGER NOT NULL REFERENCES subjects (id), -- предмет
    teacher_id     INTEGER NOT NULL REFERENCES teachers (id), -- учитель
    classroom_id   INTEGER REFERENCES classrooms (id) ON DELETE SET NULL, -- кабинет, пусто = не назначен
    note           TEXT                       -- примечание
) STRICT;

CREATE INDEX idx_extra_lessons_date ON extra_lessons (lesson_date);

DROP TRIGGER trg_substitution_room_busy_insert;
DROP TRIGGER trg_substitution_room_busy_update;

-- Кабинет и номер урока берём итоговые: замена может менять только учителя, но урок всё равно занимает кабинет
CREATE TRIGGER trg_substitution_room_busy_insert
BEFORE INSERT ON substitutions
WHEN NEW.is_cancelled = 0 AND (
    EXISTS (
        SELECT 1
        FROM schedule me
        JOIN lesson_slots a ON a.id = COALESCE(NEW.lesson_slot_id, me.lesson_slot_id)
        JOIN schedule s
            ON s.version_id = me.version_id
            AND s.week_type_id = me.week_type_id
            AND s.weekday_id = me.weekday_id
            AND s.id <> me.id
        LEFT JOIN substitutions x ON x.schedule_id = s.id AND x.lesson_date = NEW.lesson_date
        JOIN lesson_slots b ON b.id = COALESCE(x.lesson_slot_id, s.lesson_slot_id)
        WHERE me.id = NEW.schedule_id
            AND (a.id = b.id OR (a.starts_at < b.ends_at AND b.starts_at < a.ends_at))
            AND COALESCE(x.is_cancelled, 0) = 0
            AND COALESCE(x.classroom_id, s.classroom_id) = COALESCE(NEW.classroom_id, me.classroom_id)
    )
    OR EXISTS (
        SELECT 1
        FROM schedule me
        JOIN lesson_slots a ON a.id = COALESCE(NEW.lesson_slot_id, me.lesson_slot_id)
        JOIN extra_lessons e ON e.version_id = me.version_id AND e.lesson_date = NEW.lesson_date
        JOIN lesson_slots b ON b.id = e.lesson_slot_id
        WHERE me.id = NEW.schedule_id
            AND (a.id = b.id OR (a.starts_at < b.ends_at AND b.starts_at < a.ends_at))
            AND e.classroom_id = COALESCE(NEW.classroom_id, me.classroom_id)
    )
)
BEGIN
    SELECT RAISE(ABORT, 'Кабинет занят на этом уроке');
END;

CREATE TRIGGER trg_substitution_room_busy_update
BEFORE UPDATE OF schedule_id, lesson_date, classroom_id, is_cancelled, lesson_slot_id ON substitutions
WHEN NEW.is_cancelled = 0 AND (
    EXISTS (
        SELECT 1
        FROM schedule me
        JOIN lesson_slots a ON a.id = COALESCE(NEW.lesson_slot_id, me.lesson_slot_id)
        JOIN schedule s
            ON s.version_id = me.version_id
            AND s.week_type_id = me.week_type_id
            AND s.weekday_id = me.weekday_id
            AND s.id <> me.id
        LEFT JOIN substitutions x ON x.schedule_id = s.id AND x.lesson_date = NEW.lesson_date
        JOIN lesson_slots b ON b.id = COALESCE(x.lesson_slot_id, s.lesson_slot_id)
        WHERE me.id = NEW.schedule_id
            AND (a.id = b.id OR (a.starts_at < b.ends_at AND b.starts_at < a.ends_at))
            AND COALESCE(x.is_cancelled, 0) = 0
            AND COALESCE(x.classroom_id, s.classroom_id) = COALESCE(NEW.classroom_id, me.classroom_id)
    )
    OR EXISTS (
        SELECT 1
        FROM schedule me
        JOIN lesson_slots a ON a.id = COALESCE(NEW.lesson_slot_id, me.lesson_slot_id)
        JOIN extra_lessons e ON e.version_id = me.version_id AND e.lesson_date = NEW.lesson_date
        JOIN lesson_slots b ON b.id = e.lesson_slot_id
        WHERE me.id = NEW.schedule_id
            AND (a.id = b.id OR (a.starts_at < b.ends_at AND b.starts_at < a.ends_at))
            AND e.classroom_id = COALESCE(NEW.classroom_id, me.classroom_id)
    )
)
BEGIN
    SELECT RAISE(ABORT, 'Кабинет занят на этом уроке');
END;

-- IS NOT, а не <>: при вставке NEW.id ещё пустой, и сравнение через <> отбросило бы все строки
CREATE TRIGGER trg_extra_lesson_room_busy_insert
BEFORE INSERT ON extra_lessons
WHEN NEW.classroom_id IS NOT NULL AND (
    EXISTS (
        SELECT 1
        FROM lesson_slots a
        JOIN schedule s
            ON s.version_id = NEW.version_id
            AND s.week_type_id = NEW.week_type_id
            AND s.weekday_id = CAST(strftime('%u', NEW.lesson_date) AS INTEGER)
        LEFT JOIN substitutions x ON x.schedule_id = s.id AND x.lesson_date = NEW.lesson_date
        JOIN lesson_slots b ON b.id = COALESCE(x.lesson_slot_id, s.lesson_slot_id)
        WHERE a.id = NEW.lesson_slot_id
            AND (a.id = b.id OR (a.starts_at < b.ends_at AND b.starts_at < a.ends_at))
            AND COALESCE(x.is_cancelled, 0) = 0
            AND COALESCE(x.classroom_id, s.classroom_id) = NEW.classroom_id
    )
    OR EXISTS (
        SELECT 1
        FROM lesson_slots a
        JOIN extra_lessons e ON e.version_id = NEW.version_id AND e.lesson_date = NEW.lesson_date AND e.id IS NOT NEW.id
        JOIN lesson_slots b ON b.id = e.lesson_slot_id
        WHERE a.id = NEW.lesson_slot_id
            AND (a.id = b.id OR (a.starts_at < b.ends_at AND b.starts_at < a.ends_at))
            AND e.classroom_id = NEW.classroom_id
    )
)
BEGIN
    SELECT RAISE(ABORT, 'Кабинет занят на этом уроке');
END;

CREATE TRIGGER trg_extra_lesson_room_busy_update
BEFORE UPDATE OF lesson_date, lesson_slot_id, classroom_id ON extra_lessons
WHEN NEW.classroom_id IS NOT NULL AND (
    EXISTS (
        SELECT 1
        FROM lesson_slots a
        JOIN schedule s
            ON s.version_id = NEW.version_id
            AND s.week_type_id = NEW.week_type_id
            AND s.weekday_id = CAST(strftime('%u', NEW.lesson_date) AS INTEGER)
        LEFT JOIN substitutions x ON x.schedule_id = s.id AND x.lesson_date = NEW.lesson_date
        JOIN lesson_slots b ON b.id = COALESCE(x.lesson_slot_id, s.lesson_slot_id)
        WHERE a.id = NEW.lesson_slot_id
            AND (a.id = b.id OR (a.starts_at < b.ends_at AND b.starts_at < a.ends_at))
            AND COALESCE(x.is_cancelled, 0) = 0
            AND COALESCE(x.classroom_id, s.classroom_id) = NEW.classroom_id
    )
    OR EXISTS (
        SELECT 1
        FROM lesson_slots a
        JOIN extra_lessons e ON e.version_id = NEW.version_id AND e.lesson_date = NEW.lesson_date AND e.id IS NOT NEW.id
        JOIN lesson_slots b ON b.id = e.lesson_slot_id
        WHERE a.id = NEW.lesson_slot_id
            AND (a.id = b.id OR (a.starts_at < b.ends_at AND b.starts_at < a.ends_at))
            AND e.classroom_id = NEW.classroom_id
    )
)
BEGIN
    SELECT RAISE(ABORT, 'Кабинет занят на этом уроке');
END;
