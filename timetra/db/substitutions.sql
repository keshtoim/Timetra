-- Отдельный файл: таблица появилась после первых установок, в их базу она добавляется при запуске
CREATE TABLE substitutions (                  -- замены на конкретную дату
    id           INTEGER PRIMARY KEY,         -- идентификатор замены
    schedule_id  INTEGER NOT NULL REFERENCES schedule (id) ON DELETE CASCADE, -- какой урок расписания меняется
    lesson_date  TEXT NOT NULL CHECK (lesson_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'), -- дата, ГГГГ-ММ-ДД
    teacher_id   INTEGER REFERENCES teachers (id), -- заменяющий учитель, пусто = без изменений
    subject_id   INTEGER REFERENCES subjects (id), -- другой предмет, пусто = без изменений
    classroom_id INTEGER REFERENCES classrooms (id) ON DELETE SET NULL, -- другой кабинет, пусто = без изменений
    is_cancelled INTEGER NOT NULL DEFAULT 0 CHECK (is_cancelled IN (0, 1)), -- 1 = урока в этот день не будет
    note         TEXT,                        -- примечание, например причина замены
    UNIQUE (schedule_id, lesson_date)         -- у урока на дату одна замена
) STRICT;

CREATE INDEX idx_substitutions_date ON substitutions (lesson_date);

-- %u: 1 = понедельник, как weekdays.id
CREATE TRIGGER trg_substitution_weekday
BEFORE INSERT ON substitutions
WHEN CAST(strftime('%u', NEW.lesson_date) AS INTEGER) <> (SELECT weekday_id FROM schedule WHERE id = NEW.schedule_id)
BEGIN
    SELECT RAISE(ABORT, 'Дата не совпадает с днём урока');
END;

-- В этот день кабинет занят уроком с учётом других замен: чужая замена могла его освободить или занять
CREATE TRIGGER trg_substitution_room_busy_insert
BEFORE INSERT ON substitutions
WHEN NEW.classroom_id IS NOT NULL AND NEW.is_cancelled = 0 AND EXISTS (
    SELECT 1
    FROM schedule me
    JOIN schedule s
        ON s.version_id = me.version_id
        AND s.week_type_id = me.week_type_id
        AND s.weekday_id = me.weekday_id
        AND s.id <> me.id
    JOIN lesson_slots a ON a.id = me.lesson_slot_id
    JOIN lesson_slots b ON b.id = s.lesson_slot_id
    LEFT JOIN substitutions x ON x.schedule_id = s.id AND x.lesson_date = NEW.lesson_date
    WHERE me.id = NEW.schedule_id
        AND (a.id = b.id OR (a.starts_at < b.ends_at AND b.starts_at < a.ends_at))
        AND COALESCE(x.is_cancelled, 0) = 0
        AND COALESCE(x.classroom_id, s.classroom_id) = NEW.classroom_id
)
BEGIN
    SELECT RAISE(ABORT, 'Кабинет занят на этом уроке');
END;

CREATE TRIGGER trg_substitution_room_busy_update
BEFORE UPDATE OF schedule_id, lesson_date, classroom_id, is_cancelled ON substitutions
WHEN NEW.classroom_id IS NOT NULL AND NEW.is_cancelled = 0 AND EXISTS (
    SELECT 1
    FROM schedule me
    JOIN schedule s
        ON s.version_id = me.version_id
        AND s.week_type_id = me.week_type_id
        AND s.weekday_id = me.weekday_id
        AND s.id <> me.id
    JOIN lesson_slots a ON a.id = me.lesson_slot_id
    JOIN lesson_slots b ON b.id = s.lesson_slot_id
    LEFT JOIN substitutions x ON x.schedule_id = s.id AND x.lesson_date = NEW.lesson_date
    WHERE me.id = NEW.schedule_id
        AND (a.id = b.id OR (a.starts_at < b.ends_at AND b.starts_at < a.ends_at))
        AND COALESCE(x.is_cancelled, 0) = 0
        AND COALESCE(x.classroom_id, s.classroom_id) = NEW.classroom_id
)
BEGIN
    SELECT RAISE(ABORT, 'Кабинет занят на этом уроке');
END;
