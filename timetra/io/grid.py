import re
from pathlib import Path

from timetra.db.repo import Repo
from timetra.io.tables import HELP_SHEET, TableError

ODD, EVEN = 1, 2
HEAD_DAY, HEAD_LESSON = "День", "Урок"
TOP_ROW = 2  # строка 1 занята заголовком листа
FIRST_CLASS_COL = 3
HALF_WIDTH = 15
LINE_HEIGHT = 15
ACCENT, ACCENT_SOFT, BORDER, DAY_TINT = "0F6E5C", "DCEDE8", "A9BDB6", "F2F6F4"
BLOCK_RE = re.compile(r"\n\s*\n")
ROOM_RE = re.compile(r"^каб\.?\s*(.+)$", re.IGNORECASE)
GROUP_RE = re.compile(r"^(.*?)(?:,\s*гр\.?\s*(\d+))?$")
HELP_ROWS = [
    ["Как заполнять общее расписание"],
    ["Столбцы — классы, строки — дни и номера уроков. Первая половина столбца класса — нечётная неделя, вторая — чётная."],
    ["Урок на обе недели: объедините две половины клетки в одну и напишите урок в ней."],
    ["В клетке пишите с новой строки: предмет, учителя, кабинет. Например: Математика, потом Иванова М. С., потом каб. 101."],
    ["Учитель нужен только для чтения: при загрузке он берётся из раздела «Нагрузка»."],
    ["Подгруппы: после предмета добавьте номер, например Англ., гр. 1. Уроки разных подгрупп разделяйте пустой строкой."],
    ["Предметы, классы и кабинеты должны уже быть в программе, а уроки — в разделе «Нагрузка»."],
]


def _lesson_block(row) -> str:
    group = f", гр. {row['subgroup']}" if row["subgroup"] else ""
    lines = [f"{row['subject_short']}{group}", row["teacher_short"]]
    if row["room_number"]:
        lines.append(f"каб. {row['room_number']}")
    return "\n".join(lines)


def _is_every_week(lessons) -> bool:
    """Обе половины клетки совпадают: тогда пишем урок в объединённую клетку."""
    odd = sorted((x["workload_id"], x["classroom_id"] or 0) for x in lessons if x["week_type_id"] == ODD)
    even = sorted((x["workload_id"], x["classroom_id"] or 0) for x in lessons if x["week_type_id"] == EVEN)
    return odd == even


def _cell_text(lessons) -> str:
    return "\n\n".join(_lesson_block(x) for x in sorted(lessons, key=lambda x: x["subgroup"]))


def write_schedule_grid(repo: Repo, version, path: Path, empty: bool = False) -> None:
    """Общее расписание школы для печати. empty=True — такая же сетка без уроков, это шаблон."""
    if path.suffix.lower() != ".xlsx":
        raise TableError("Общее расписание сохраняется только в формате .xlsx.")
    classes = repo.classes()
    if not classes:
        raise TableError("Сначала добавьте классы в разделе «Справочники».")
    import openpyxl

    book = openpyxl.Workbook()
    book.remove(book.active)
    days = [d for d in repo.weekdays() if d["id"] <= max(x["study_days"] for x in classes)]
    shifts = {s["id"]: s["name"] for s in repo.shifts()}
    used = sorted({x["shift_id"] for x in classes})
    lessons = [] if empty else repo.lessons(version)
    for shift in used:
        title = "Расписание" if len(used) == 1 else f"{shifts[shift]} смена"
        members = [x for x in classes if x["shift_id"] == shift]
        _fill_sheet(book.create_sheet(title), members, days, repo.slots(shift), lessons)
    if empty:
        notes = book.create_sheet(HELP_SHEET)
        for row in HELP_ROWS:
            notes.append(row)
        notes.column_dimensions["A"].width = 120
        notes["A1"].font = openpyxl.styles.Font(bold=True, size=13)
    try:
        book.save(path)
    except PermissionError as error:
        raise TableError("Файл открыт в другой программе. Закройте его и попробуйте ещё раз.") from error
    except OSError as error:
        raise TableError("Файл не удалось сохранить. Выберите другую папку.") from error


def _fill_sheet(sheet, classes, days, slots, lessons) -> None:
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    thin, thick = Side(style="thin", color=BORDER), Side(style="medium", color=ACCENT)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    head_fill, soft_fill, tint = (PatternFill("solid", fgColor=x) for x in (ACCENT, ACCENT_SOFT, DAY_TINT))
    last_col = FIRST_CLASS_COL + len(classes) * 2 - 1

    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_col)
    sheet.cell(1, 1, "Расписание уроков").font = Font(bold=True, size=16, color=ACCENT)
    sheet.cell(1, 1).alignment = center
    sheet.row_dimensions[1].height = 28

    sub_row = TOP_ROW + 1
    sheet.merge_cells(start_row=TOP_ROW, start_column=1, end_row=sub_row, end_column=1)
    sheet.merge_cells(start_row=TOP_ROW, start_column=2, end_row=sub_row, end_column=2)
    sheet.cell(TOP_ROW, 1, HEAD_DAY)
    sheet.cell(TOP_ROW, 2, HEAD_LESSON)
    for i, cls in enumerate(classes):
        col = FIRST_CLASS_COL + i * 2
        sheet.merge_cells(start_row=TOP_ROW, start_column=col, end_row=TOP_ROW, end_column=col + 1)
        sheet.cell(TOP_ROW, col, cls["name"])
        sheet.cell(sub_row, col, "нечётная")
        sheet.cell(sub_row, col + 1, "чётная")
        sheet.column_dimensions[get_column_letter(col)].width = HALF_WIDTH
        sheet.column_dimensions[get_column_letter(col + 1)].width = HALF_WIDTH
    for col in range(1, last_col + 1):
        top = sheet.cell(TOP_ROW, col)
        top.fill, top.font, top.alignment = head_fill, Font(bold=True, color="FFFFFF", size=12), center
        top.border = Border(left=thin, right=thin, top=thin, bottom=thin)
        sub = sheet.cell(sub_row, col)
        sub.alignment, sub.border = center, Border(left=thin, right=thin, top=thin, bottom=thin)
        if col < FIRST_CLASS_COL:
            sub.fill = head_fill
        else:
            sub.fill, sub.font = soft_fill, Font(size=9, color=ACCENT)
    sheet.column_dimensions["A"].width = 6
    sheet.column_dimensions["B"].width = 12

    by_cell: dict[tuple, list] = {}
    for row in lessons:
        by_cell.setdefault((row["class_id"], row["weekday_id"], row["lesson_slot_id"]), []).append(row)

    row = sub_row + 1
    for d, day in enumerate(days):
        first_row = row
        for s, slot in enumerate(slots):
            top = thick if s == 0 else thin
            # без времени пишем числом, иначе Excel помечает клетку как "число в виде текста"
            caption = f"{slot['number']}\n{slot['starts_at']}–{slot['ends_at'] or ''}" if slot["starts_at"] else slot["number"]
            lesson_cell = sheet.cell(row, 2, caption)
            lesson_cell.alignment, lesson_cell.font = center, Font(bold=True, size=9)
            lesson_cell.fill = soft_fill
            lesson_cell.border = Border(left=thin, right=thin, top=top, bottom=thin)
            height = 2
            for i, cls in enumerate(classes):
                col = FIRST_CLASS_COL + i * 2
                items = by_cell.get((cls["id"], day["id"], slot["id"]), [])
                height = max(height, _write_class_cell(sheet, row, col, items, center))
                for half in (col, col + 1):
                    cell = sheet.cell(row, half)
                    cell.border = Border(left=thin, right=thin, top=top, bottom=thin)
                    cell.font = Font(size=9)
                    if d % 2:
                        cell.fill = tint
            sheet.row_dimensions[row].height = height * LINE_HEIGHT
            row += 1
        sheet.merge_cells(start_row=first_row, start_column=1, end_row=row - 1, end_column=1)
        day_cell = sheet.cell(first_row, 1, day["name"])
        day_cell.fill = head_fill
        day_cell.font = Font(bold=True, color="FFFFFF", size=12)
        day_cell.alignment = Alignment(horizontal="center", vertical="center", text_rotation=90)
        day_cell.border = Border(left=thin, right=thin, top=thick, bottom=thin)

    sheet.freeze_panes = sheet.cell(sub_row + 1, FIRST_CLASS_COL)
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.print_title_rows = f"{TOP_ROW}:{sub_row}"


def _write_class_cell(sheet, row, col, items, center) -> int:
    """Возвращает высоту клетки в строках текста."""
    if _is_every_week(items):
        sheet.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + 1)
        text = _cell_text([x for x in items if x["week_type_id"] == ODD])
        sheet.cell(row, col, text or None).alignment = center
        return text.count("\n") + 1
    height = 1
    for week, half in ((ODD, col), (EVEN, col + 1)):
        text = _cell_text([x for x in items if x["week_type_id"] == week])
        sheet.cell(row, half, text or None).alignment = center
        height = max(height, text.count("\n") + 1)
    return height


def read_schedule_grid(path: Path) -> list[list[str]]:
    """Сетка в виде таблицы вида "Расписание": дальше её разбирает общий код импорта."""
    if path.suffix.lower() != ".xlsx":
        raise TableError("Общее расписание загружается только из файла .xlsx.")
    try:
        import openpyxl

        # read_only здесь нельзя: в этом режиме не видно объединённых клеток
        book = openpyxl.load_workbook(path, data_only=True)
    except PermissionError as error:
        raise TableError("Файл открыт в другой программе. Закройте его и попробуйте ещё раз.") from error
    except OSError as error:
        raise TableError("Файл не удалось открыть.") from error
    except Exception as error:
        raise TableError("Файл повреждён или это не таблица. Попробуйте скачать шаблон и заполнить его.") from error
    rows = [["Неделя", "День", "Номер урока", "Класс", "Предмет", "Группа", "Кабинет"]]
    found = False
    for sheet in book.worksheets:
        head = _find_head(sheet)
        if head:
            found = True
            rows.extend(_read_sheet(sheet, head))
    book.close()
    if not found:
        raise TableError(f"В файле нет сетки расписания: нужны столбцы «{HEAD_DAY}» и «{HEAD_LESSON}». Скачайте шаблон и заполните его.")
    return rows


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _find_head(sheet) -> int | None:
    for row in range(1, min(sheet.max_row, 10) + 1):
        if _text(sheet.cell(row, 1).value) == HEAD_DAY and _text(sheet.cell(row, 2).value) == HEAD_LESSON:
            return row
    return None


def _read_sheet(sheet, head: int):
    merged = {}
    for area in sheet.merged_cells.ranges:
        merged[(area.min_row, area.min_col)] = area
    classes = []
    col = FIRST_CLASS_COL
    while col <= sheet.max_column:
        name = _text(sheet.cell(head, col).value)
        area = merged.get((head, col))
        span = area.max_col - area.min_col + 1 if area else 1
        if name:
            classes.append((name, col, span))
        col += span
    start = head + 1
    # строка с подписями недель необязательна: в своей таблице её может не быть
    if "неч" in _text(sheet.cell(head + 1, FIRST_CLASS_COL).value).lower():
        start = head + 2
    day = ""
    for row in range(start, sheet.max_row + 1):
        day = _text(sheet.cell(row, 1).value) or day
        number = re.match(r"\d+", _text(sheet.cell(row, 2).value))
        if not number:
            continue
        for name, col, span in classes:
            area = merged.get((row, col))
            if span == 1 or (area and area.max_col > col):
                yield from _read_cell(sheet.cell(row, col).value, "Обе", day, number[0], name)
            else:
                yield from _read_cell(sheet.cell(row, col).value, "Нечётная", day, number[0], name)
                yield from _read_cell(sheet.cell(row, col + 1).value, "Чётная", day, number[0], name)


def _read_cell(value, week, day, number, class_name):
    for block in BLOCK_RE.split(_text(value)):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        match = GROUP_RE.match(lines[0])
        room = ""
        for line in lines[1:]:
            found = ROOM_RE.match(line)
            if found:
                room = found[1].strip()
        yield [week, day, number, class_name, match[1].strip(), match[2] or "", room]
