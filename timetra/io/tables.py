import csv
import datetime
from pathlib import Path

CSV_DELIMITERS = ";,\t"
TEXT_ENCODINGS = ("utf-8-sig", "cp1251")  # файлы из русского Excel часто в cp1251


class TableError(Exception):
    """Файл не удалось прочитать или записать. Текст показывается пользователю."""


def _cell_to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    # Excel хранит все числа как дробные: 5 приходит как 5.0
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (datetime.time, datetime.datetime)):
        return value.strftime("%H:%M")
    return str(value).strip()


def read_table(path: Path) -> list[list[str]]:
    """Строки первого листа как текст, полностью пустые строки отброшены."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".xlsx":
            rows = _read_xlsx(path)
        elif suffix == ".xls":
            rows = _read_xls(path)
        elif suffix in (".csv", ".txt"):
            rows = _read_text(path)
        else:
            raise TableError("Такой формат не подходит. Выберите файл .xlsx, .xls, .csv или .txt.")
    except PermissionError as error:
        raise TableError("Файл открыт в другой программе. Закройте его и попробуйте ещё раз.") from error
    except OSError as error:
        raise TableError("Файл не удалось открыть.") from error
    except TableError:
        raise
    except Exception as error:
        # библиотеки Excel бросают свои типы ошибок на испорченных файлах
        raise TableError("Файл повреждён или это не таблица. Попробуйте скачать шаблон и заполнить его.") from error
    cleaned = [[_cell_to_text(v) for v in row] for row in rows]
    return [row for row in cleaned if any(row)]


def _read_xlsx(path: Path):
    import openpyxl

    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        return [list(row) for row in book.worksheets[0].iter_rows(values_only=True)]
    finally:
        book.close()


def _read_xls(path: Path):
    import xlrd

    book = xlrd.open_workbook(str(path))
    sheet = book.sheet_by_index(0)
    return [sheet.row_values(i) for i in range(sheet.nrows)]


def _read_text(path: Path):
    data = path.read_bytes()
    for encoding in TEXT_ENCODINGS:
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise TableError("Не удалось определить кодировку файла. Сохраните его в UTF-8.")
    lines = text.splitlines()
    head = lines[0] if lines else ""
    delimiter = max(CSV_DELIMITERS, key=head.count)
    return list(csv.reader(lines, delimiter=delimiter))


def write_table(path: Path, head: list[str], rows: list[list], help_rows: list[list[str]] | None = None) -> None:
    """help_rows попадают на второй лист в Excel-форматах; в csv и txt листов нет."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".xlsx":
            _write_xlsx(path, head, rows, help_rows)
        elif suffix == ".xls":
            _write_xls(path, head, rows, help_rows)
        elif suffix in (".csv", ".txt"):
            # точка с запятой и BOM: так русский Excel открывает csv без "кракозябр" и в разных столбцах
            with path.open("w", newline="", encoding="utf-8-sig") as file:
                writer = csv.writer(file, delimiter=";" if suffix == ".csv" else "\t")
                writer.writerow(head)
                writer.writerows(rows)
        else:
            raise TableError("Такой формат не подходит. Выберите .xlsx, .xls, .csv или .txt.")
    except PermissionError as error:
        raise TableError("Файл открыт в другой программе. Закройте его и попробуйте ещё раз.") from error
    except OSError as error:
        raise TableError("Файл не удалось сохранить. Выберите другую папку.") from error


def _write_xlsx(path, head, rows, help_rows):
    import openpyxl
    from openpyxl.styles import Font

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Данные"
    sheet.append(head)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append(row)
    table = [head, *rows]
    for i in range(len(head)):
        width = max(len(str(r[i])) if i < len(r) and r[i] is not None else 0 for r in table)
        sheet.column_dimensions[openpyxl.utils.get_column_letter(i + 1)].width = width + 3
    if help_rows:
        notes = book.create_sheet("Как заполнять")
        for row in help_rows:
            notes.append(row)
        for cell in notes[1]:
            cell.font = Font(bold=True)
        for column, width in zip("ABCD", (24, 14, 60, 24)):
            notes.column_dimensions[column].width = width
    book.save(path)


def _write_xls(path, head, rows, help_rows):
    import xlwt

    book = xlwt.Workbook(encoding="utf-8")
    bold = xlwt.easyxf("font: bold on")
    sheet = book.add_sheet("Данные")
    for col, title in enumerate(head):
        sheet.write(0, col, title, bold)
        sheet.col(col).width = 256 * (len(title) + 8)
    for r, row in enumerate(rows, start=1):
        for col, value in enumerate(row):
            sheet.write(r, col, value)
    if help_rows:
        notes = book.add_sheet("Как заполнять")
        for r, row in enumerate(help_rows):
            for col, value in enumerate(row):
                notes.write(r, col, value, bold if r == 0 else xlwt.Style.default_style)
        for col, width in enumerate((24, 14, 60, 24)):
            notes.col(col).width = 256 * width
    book.save(str(path))
