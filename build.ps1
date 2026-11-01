# Сборка в dist\Timetra. Один каталог вместо одного exe: так программа запускается заметно быстрее.
.\.venv\Scripts\python.exe -m pip install --quiet --disable-pip-version-check -e ".[dev]"
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name Timetra `
    --add-data "timetra/db/schema.sql;timetra/db" `
    --exclude-module unittest --exclude-module pydoc --exclude-module test `
    timetra/main.py
