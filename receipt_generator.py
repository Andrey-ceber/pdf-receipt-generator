#!/usr/bin/env python3
"""Generate receipt HTML/PDF files from HTML templates and CSV data."""

from __future__ import annotations

import argparse
import contextlib
import csv
import html
import json
import os
import platform
import re
import subprocess
import sys
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "receipt_config.json"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "output"
SUPPORTED_HTML = {".html", ".htm"}
CSV_ENCODINGS = ("utf-8-sig", "utf-8", "cp1251")
DELIMITERS = ",;\t"
PLACEHOLDER_RE = re.compile(r"{{\s*([A-Za-zА-Яа-яЁё0-9_. -]+)\s*}}")
BAD_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

SKIP_DIR_NAMES = {
    "$recycle.bin",
    ".cache",
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "appdata",
    "application data",
    "library",
    "node_modules",
    "program files",
    "program files (x86)",
    "programdata",
    "system volume information",
    "windows",
}

PRINT_CSS = """
<style>
@page {
    size: A4;
    margin: 12mm;
}

body {
    font-family: var(--receipt-font, "Roboto", "Liberation Sans", "DejaVu Sans", Arial, sans-serif);
    font-size: 11pt;
    line-height: 1.35;
}

table {
    width: 100%;
    border-collapse: collapse;
    table-layout: fixed;
}

th,
td {
    border: 1px solid #444;
    padding: 6px;
    text-align: center;
    vertical-align: middle;
    overflow-wrap: anywhere;
    word-break: break-word;
    white-space: normal;
}

thead {
    display: table-header-group;
}

tr {
    break-inside: avoid;
    page-break-inside: avoid;
}
</style>
"""


@dataclass
class CsvData:
    path: Path
    encoding: str
    delimiter: str
    headers: list[str]
    rows: list[dict[str, str]]


@dataclass
class FileInfo:
    path: Path
    modified: str
    placeholders: list[str] | None = None
    csv_rows: int | None = None
    csv_headers: list[str] | None = None
    csv_error: str | None = None


@dataclass
class GenerationResult:
    html_files: list[Path]
    pdf_files: list[Path]
    errors: list[str]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Формирование чеков PDF из HTML-шаблона и CSV-файла."
    )
    parser.add_argument("--template", help="Путь к HTML-шаблону")
    parser.add_argument("--data", help="Путь к CSV-файлу")
    parser.add_argument("--row", type=int, help="Одна строка CSV, 1-based")
    parser.add_argument("--rows", help='Строки CSV, например "1,3,5-10"')
    parser.add_argument("--all", action="store_true", help="Сформировать все строки")
    parser.add_argument("--output", help="Папка вывода")
    args = parser.parse_args()

    try:
        if args.template or args.data or args.row or args.rows or args.all:
            run_cli(args)
        else:
            run_interactive()
    except KeyboardInterrupt:
        print("\nОперация отменена пользователем.")


def run_cli(args: argparse.Namespace) -> None:
    if not args.template or not args.data:
        raise SystemExit("Для быстрого запуска укажите --template и --data.")
    selectors = [bool(args.row), bool(args.rows), args.all]
    if sum(selectors) != 1:
        raise SystemExit("Укажите ровно один вариант выбора строк: --row, --rows или --all.")

    template_path = Path(args.template).expanduser().resolve()
    csv_path = Path(args.data).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve() if args.output else DEFAULT_OUTPUT_DIR
    ensure_existing_file(template_path, "HTML-шаблон")
    ensure_existing_file(csv_path, "CSV-файл")

    template_text = read_text_file(template_path)
    placeholders = find_placeholders(template_text)
    csv_data = read_csv_data(csv_path)
    mapping, constants = build_mapping(placeholders, csv_data.headers, load_config(), interactive=False)
    if not mapping_is_complete(placeholders, mapping, constants):
        missing = find_unmapped(placeholders, mapping, constants)
        raise SystemExit(f"Не удалось сопоставить плейсхолдеры: {', '.join(missing)}")

    if args.all:
        selected_indices = list(range(len(csv_data.rows)))
    elif args.row:
        selected_indices = parse_row_selection(str(args.row), len(csv_data.rows))
    else:
        selected_indices = parse_row_selection(args.rows, len(csv_data.rows))

    name_column = choose_name_column(csv_data.headers, load_config(), interactive=False)
    result = generate_receipts(
        template_path=template_path,
        template_text=template_text,
        csv_data=csv_data,
        row_indices=selected_indices,
        output_dir=output_dir,
        mapping=mapping,
        constants=constants,
        name_column=name_column,
        interactive_conflicts=False,
    )
    print_report(result, output_dir)
    auto_open_generation_result(result, output_dir)
    save_config(
        {
            "previous_directories": unique_paths([str(template_path.parent), str(csv_path.parent)]),
            "last_template": str(template_path),
            "last_csv": str(csv_path),
            "output_dir": str(output_dir),
            "placeholder_mapping": mapping,
            "placeholder_constants": constants,
            "filename_column": name_column,
        }
    )


def run_interactive() -> None:
    config = load_config()
    while True:
        print("\nГенератор чеков")
        if config.get("last_template") and config.get("last_csv"):
            print("1. Повторить предыдущую настройку")
            print("2. Выбрать другой шаблон или CSV")
            print("3. Выполнить новое сканирование")
            print("0. Выход")
            choice = input_choice("Выберите действие: ", {"0", "1", "2", "3"})
        else:
            print("1. Выполнить новое сканирование")
            print("0. Выход")
            choice = input_choice("Выберите действие: ", {"0", "1"})
            if choice == "1":
                choice = "3"

        if choice == "0":
            return
        if choice == "1":
            if run_previous_config(config):
                config = load_config()
            continue

        html_files, csv_files, directories = scan_flow(config)
        if not html_files or not csv_files:
            continue
        template_info = choose_from_list("Доступные HTML-шаблоны чеков", html_files)
        csv_info = choose_from_list("Доступные CSV-файлы", csv_files)
        run_generation_flow(template_info.path, csv_info.path, directories, config)
        config = load_config()


def run_previous_config(config: dict[str, Any]) -> bool:
    try:
        template_path = resolve_config_path(config["last_template"])
        csv_path = resolve_config_path(config["last_csv"])
        ensure_existing_file(template_path, "HTML-шаблон")
        ensure_existing_file(csv_path, "CSV-файл")
    except Exception as exc:
        print(f"Предыдущую настройку нельзя использовать: {exc}")
        return False
    return run_generation_flow(
        template_path,
        csv_path,
        [template_path.parent, csv_path.parent],
        config,
        prefer_saved=True,
    )


def run_generation_flow(
    template_path: Path,
    csv_path: Path,
    directories: list[Path],
    config: dict[str, Any],
    prefer_saved: bool = False,
) -> bool:
    try:
        template_text = read_text_file(template_path)
        placeholders = find_placeholders(template_text)
        csv_data = read_csv_data(csv_path)
    except Exception as exc:
        print(f"Ошибка чтения файлов: {exc}")
        return False

    print_csv_preview(csv_data, config)
    row_indices = select_rows_flow(csv_data)
    if row_indices is None:
        return False

    mapping, constants = build_mapping(
        placeholders,
        csv_data.headers,
        config if prefer_saved else {},
        interactive=True,
    )
    if not mapping_is_complete(placeholders, mapping, constants):
        print("Генерация отменена: остались несопоставленные плейсхолдеры.")
        return False

    output_dir = choose_output_dir(config)
    name_column = choose_name_column(csv_data.headers, config, interactive=True)
    receipt_numbers = [make_record_label(csv_data.rows[i], i, name_column) for i in row_indices]
    print_confirmation(template_path, csv_path, row_indices, receipt_numbers, output_dir)
    if not ask_yes_no("Начать формирование? [Да/Нет]: "):
        print("Формирование отменено.")
        return False

    result = generate_receipts(
        template_path=template_path,
        template_text=template_text,
        csv_data=csv_data,
        row_indices=row_indices,
        output_dir=output_dir,
        mapping=mapping,
        constants=constants,
        name_column=name_column,
        interactive_conflicts=True,
    )
    print_report(result, output_dir)
    auto_open_generation_result(result, output_dir)
    save_config(
        {
            "previous_directories": unique_paths([*(str(p) for p in directories), str(template_path.parent), str(csv_path.parent)]),
            "last_template": str(template_path),
            "last_csv": str(csv_path),
            "output_dir": str(output_dir),
            "placeholder_mapping": mapping,
            "placeholder_constants": constants,
            "filename_column": name_column,
        }
    )
    post_generation_menu(result, output_dir)
    return True


def scan_flow(config: dict[str, Any]) -> tuple[list[FileInfo], list[FileInfo], list[Path]]:
    directories: list[Path] = []
    while True:
        print("\nГде искать файлы?")
        print("1. Папка, где находится скрипт")
        print("2. Указать одну или несколько директорий")
        print("3. Выбрать директорию через окно выбора папки")
        print("4. Использовать директории предыдущего запуска")
        print("5. Начать поиск")
        print("0. Назад")
        print_selected_dirs(directories)
        choice = input_choice("Выберите действие: ", {"0", "1", "2", "3", "4", "5"})
        if choice == "0":
            return [], [], []
        if choice == "1":
            directories.append(SCRIPT_DIR)
        elif choice == "2":
            raw = input("Введите пути через ; : ").strip()
            for part in raw.split(";"):
                if part.strip():
                    directories.append(Path(part.strip()).expanduser())
        elif choice == "3":
            chosen = choose_directory_dialog()
            if chosen:
                directories.append(chosen)
        elif choice == "4":
            for p in config.get("previous_directories", []):
                directories.append(Path(p).expanduser())
        elif choice == "5":
            directories = unique_existing_dirs(directories)
            if not directories:
                print("Не выбраны существующие директории.")
                continue
            break

    html_files, csv_files = scan_directories(directories)
    print_file_lists(html_files, csv_files)
    if not html_files:
        print("HTML-шаблоны не найдены.")
    if not csv_files:
        print("CSV-файлы не найдены.")
    return html_files, csv_files, directories


def scan_directories(directories: list[Path]) -> tuple[list[FileInfo], list[FileInfo]]:
    html_files: list[FileInfo] = []
    csv_files: list[FileInfo] = []
    for directory in directories:
        if not directory.exists():
            print(f"Директория не существует: {directory}")
            continue
        for path in iter_files(directory):
            suffix = path.suffix.lower()
            if suffix in SUPPORTED_HTML:
                try:
                    text = read_text_file(path)
                    placeholders = find_placeholders(text)
                    html_files.append(FileInfo(path, format_mtime(path), placeholders=placeholders))
                except Exception as exc:
                    html_files.append(FileInfo(path, format_mtime(path), placeholders=[], csv_error=str(exc)))
            elif suffix == ".csv":
                try:
                    data = read_csv_data(path)
                    csv_files.append(
                        FileInfo(
                            path,
                            format_mtime(path),
                            csv_rows=len(data.rows),
                            csv_headers=data.headers,
                        )
                    )
                except Exception as exc:
                    csv_files.append(FileInfo(path, format_mtime(path), csv_error=str(exc)))
    html_files.sort(key=lambda item: str(item.path).lower())
    csv_files.sort(key=lambda item: str(item.path).lower())
    return html_files, csv_files


def iter_files(root: Path):
    stack = [root.resolve()]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if is_hidden_or_system(entry):
                continue
            if entry.is_dir():
                stack.append(entry)
            elif entry.is_file():
                yield entry


def is_hidden_or_system(path: Path) -> bool:
    name = path.name.lower()
    if name.startswith(".") or name in SKIP_DIR_NAMES:
        return True
    parts = {part.lower() for part in path.parts}
    if parts & SKIP_DIR_NAMES:
        return True
    if platform.system() == "Windows":
        try:
            import ctypes

            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
            if attrs != -1 and attrs & 0x2:
                return True
        except Exception:
            pass
    return False


def read_csv_data(path: Path) -> CsvData:
    last_error: Exception | None = None
    for encoding in CSV_ENCODINGS:
        try:
            text = path.read_text(encoding=encoding)
            if not text.strip():
                raise ValueError("CSV-файл пустой.")
            sample = text[:4096]
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=DELIMITERS)
                delimiter = dialect.delimiter
            except csv.Error:
                delimiter = guess_delimiter(sample)
            reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
            if not reader.fieldnames:
                raise ValueError("В CSV не найдены заголовки колонок.")
            headers = [header.strip() for header in reader.fieldnames if header and header.strip()]
            if not headers:
                raise ValueError("Заголовки CSV пустые.")
            rows: list[dict[str, str]] = []
            for row in reader:
                normalized = {key.strip(): (value or "").strip() for key, value in row.items() if key}
                if any(normalized.values()):
                    rows.append(normalized)
            if not rows:
                raise ValueError("CSV не содержит строк с данными.")
            return CsvData(path, encoding, delimiter, headers, rows)
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        except csv.Error as exc:
            raise ValueError(f"CSV повреждён или имеет некорректную структуру: {exc}") from exc
    raise ValueError(f"Не удалось прочитать CSV в кодировках UTF-8/UTF-8 BOM/Windows-1251: {last_error}")


def guess_delimiter(sample: str) -> str:
    counts = {delimiter: sample.count(delimiter) for delimiter in DELIMITERS}
    return max(counts, key=counts.get) if any(counts.values()) else ";"


def read_text_file(path: Path) -> str:
    last_error: Exception | None = None
    for encoding in CSV_ENCODINGS:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise ValueError(f"Не удалось прочитать файл как UTF-8/Windows-1251: {last_error}")


def find_placeholders(template_text: str) -> list[str]:
    return sorted({match.group(1).strip() for match in PLACEHOLDER_RE.finditer(template_text)})


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def build_mapping(
    placeholders: list[str],
    headers: list[str],
    config: dict[str, Any],
    interactive: bool,
) -> tuple[dict[str, str], dict[str, str]]:
    header_by_norm = {normalize_name(header): header for header in headers}
    saved_mapping = config.get("placeholder_mapping", {}) if config else {}
    saved_constants = config.get("placeholder_constants", {}) if config else {}
    mapping: dict[str, str] = {}
    constants: dict[str, str] = {}

    for placeholder in placeholders:
        saved_col = saved_mapping.get(placeholder)
        if saved_col in headers:
            mapping[placeholder] = saved_col
            continue
        if placeholder in saved_constants:
            constants[placeholder] = str(saved_constants[placeholder])
            continue
        matched = header_by_norm.get(normalize_name(placeholder))
        if matched:
            mapping[placeholder] = matched

    missing = find_unmapped(placeholders, mapping, constants)
    if missing and interactive:
        print("\nНе удалось автоматически сопоставить плейсхолдеры:")
        for placeholder in missing:
            print(f"- {placeholder}")
        print_columns(headers)
        for placeholder in missing:
            while True:
                print(f"\nПлейсхолдер: {{{{{placeholder}}}}}")
                print("1. Выбрать колонку CSV")
                print("2. Ввести постоянное значение")
                print("3. Оставить пустым")
                print("4. Отменить генерацию")
                choice = input_choice("Выберите действие: ", {"1", "2", "3", "4"})
                if choice == "1":
                    col = choose_column(headers, "Номер колонки: ")
                    mapping[placeholder] = col
                    break
                if choice == "2":
                    constants[placeholder] = input("Постоянное значение: ")
                    break
                if choice == "3":
                    constants[placeholder] = ""
                    break
                raise SystemExit("Генерация отменена пользователем.")
    return mapping, constants


def mapping_is_complete(placeholders: list[str], mapping: dict[str, str], constants: dict[str, str]) -> bool:
    return not find_unmapped(placeholders, mapping, constants)


def find_unmapped(placeholders: list[str], mapping: dict[str, str], constants: dict[str, str]) -> list[str]:
    return [placeholder for placeholder in placeholders if placeholder not in mapping and placeholder not in constants]


def select_rows_flow(csv_data: CsvData) -> list[int] | None:
    while True:
        print("\nВыбор чеков")
        print("1. Одна строка CSV")
        print("2. Несколько строк через запятую")
        print("3. Диапазон строк")
        print("4. Все строки")
        print("5. Найти запись по значению")
        print("6. Отфильтровать записи по значению колонки")
        print("7. Вернуться к выбору другого CSV-файла или HTML-шаблона")
        choice = input_choice("Выберите действие: ", {"1", "2", "3", "4", "5", "6", "7"})
        if choice == "7":
            return None
        if choice == "4":
            return list(range(len(csv_data.rows)))
        if choice in {"1", "2", "3"}:
            raw = input("Введите номер, список или диапазон строк: ").strip()
            try:
                return parse_row_selection(raw, len(csv_data.rows))
            except ValueError as exc:
                print(f"Ошибка: {exc}")
        if choice in {"5", "6"}:
            column = choose_column(csv_data.headers, "Колонка для поиска/фильтра: ")
            value = input("Значение для поиска: ").strip().lower()
            exact = choice == "5"
            matched = [
                idx
                for idx, row in enumerate(csv_data.rows)
                if (row.get(column, "").strip().lower() == value if exact else value in row.get(column, "").strip().lower())
            ]
            if matched:
                print(f"Найдено записей: {len(matched)}")
                return matched
            print("Записи не найдены.")


def parse_row_selection(raw: str, row_count: int) -> list[int]:
    if not raw or not raw.strip():
        raise ValueError("Пустой выбор строк.")
    selected: set[int] = set()
    for part in raw.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start, end = int(start_text), int(end_text)
            if start > end:
                start, end = end, start
            selected.update(range(start, end + 1))
        else:
            selected.add(int(part))
    invalid = [num for num in selected if num < 1 or num > row_count]
    if invalid:
        raise ValueError(f"Номера строк вне диапазона 1-{row_count}: {invalid}")
    return [num - 1 for num in sorted(selected)]


def generate_receipts(
    template_path: Path,
    template_text: str,
    csv_data: CsvData,
    row_indices: list[int],
    output_dir: Path,
    mapping: dict[str, str],
    constants: dict[str, str],
    name_column: str | None,
    interactive_conflicts: bool,
) -> GenerationResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    if not os.access(output_dir, os.W_OK):
        raise SystemExit(f"Нет прав на запись в директорию: {output_dir}")

    html_files: list[Path] = []
    pdf_files: list[Path] = []
    errors: list[str] = []
    conflict_action_all: str | None = None
    font_css = build_font_css()
    printable_template = inject_print_css(template_text, font_css + PRINT_CSS)

    try:
        with suppress_native_stderr():
            from weasyprint import HTML
    except ImportError as exc:
        raise SystemExit(
            "WeasyPrint не установлен. Установите зависимости командой: "
            "python -m pip install -r requirements.txt"
        ) from exc

    for row_idx in row_indices:
        row = csv_data.rows[row_idx]
        label = make_record_label(row, row_idx, name_column)
        base_name = sanitize_filename(f"receipt_{label}") or f"receipt_row_{row_idx + 1}"
        html_path = output_dir / f"{base_name}.html"
        pdf_path = output_dir / f"{base_name}.pdf"
        try:
            html_path, pdf_path, conflict_action_all = resolve_conflicts(
                html_path,
                pdf_path,
                interactive_conflicts,
                conflict_action_all,
            )
            if html_path is None or pdf_path is None:
                continue
            rendered = render_template(printable_template, row, mapping, constants)
            html_path.write_text(rendered, encoding="utf-8")
            with suppress_native_stderr():
                HTML(filename=str(html_path), base_url=str(template_path.parent)).write_pdf(str(pdf_path))
            html_files.append(html_path)
            pdf_files.append(pdf_path)
        except PermissionError:
            errors.append(f"Файл занят или нет прав на запись: {pdf_path}")
        except Exception as exc:
            errors.append(f"Строка {row_idx + 1}: PDF не удалось создать: {exc}")
    return GenerationResult(html_files, pdf_files, errors)


def render_template(
    template_text: str,
    row: dict[str, str],
    mapping: dict[str, str],
    constants: dict[str, str],
) -> str:
    def replace(match: re.Match[str]) -> str:
        placeholder = match.group(1).strip()
        if placeholder in mapping:
            return html.escape(row.get(mapping[placeholder], ""), quote=True)
        return html.escape(constants.get(placeholder, ""), quote=True)

    return PLACEHOLDER_RE.sub(replace, template_text)


def inject_print_css(template_text: str, css: str) -> str:
    if "</head>" in template_text.lower():
        return re.sub(r"</head>", css + "\n</head>", template_text, count=1, flags=re.IGNORECASE)
    return css + "\n" + template_text


def build_font_css() -> str:
    font_path = find_font_file()
    if not font_path:
        print("Предупреждение: Roboto/Liberation Sans/DejaVu Sans не найдены. Будет использован системный sans-serif.")
        return ""
    family = font_family_from_path(font_path)
    return f"""
<style>
@font-face {{
    font-family: "{family}";
    src: url("{font_path.as_uri()}");
}}
:root {{
    --receipt-font: "{family}";
}}
</style>
"""


def find_font_file() -> Path | None:
    candidates: list[Path] = []
    search_dirs = [SCRIPT_DIR / "fonts"]
    system = platform.system()
    if system == "Windows":
        search_dirs.append(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts")
    elif system == "Darwin":
        search_dirs.extend([Path("/Library/Fonts"), Path.home() / "Library/Fonts", Path("/System/Library/Fonts")])

    preferred = (
        "Roboto-Regular",
        "Roboto",
        "LiberationSans-Regular",
        "Liberation Sans",
        "DejaVuSans",
        "DejaVu Sans",
        "arial",
        "times",
    )
    for directory in search_dirs:
        if not directory.exists():
            continue
        for ext in ("*.ttf", "*.otf", "*.ttc"):
            candidates.extend(directory.glob(ext))
    for name in preferred:
        for font in candidates:
            if name.lower().replace(" ", "") in font.stem.lower().replace(" ", ""):
                return font.resolve()
    return None


def font_family_from_path(path: Path) -> str:
    stem = path.stem.lower()
    if "roboto" in stem:
        return "Roboto"
    if "liberation" in stem:
        return "Liberation Sans"
    if "dejavu" in stem:
        return "DejaVu Sans"
    if "arial" in stem:
        return "Arial"
    if "times" in stem:
        return "Times New Roman"
    return path.stem


def resolve_conflicts(
    html_path: Path,
    pdf_path: Path,
    interactive: bool,
    action_all: str | None,
) -> tuple[Path | None, Path | None, str | None]:
    if not html_path.exists() and not pdf_path.exists():
        return html_path, pdf_path, action_all
    action = action_all
    if not action:
        if not interactive:
            action = "number"
        else:
            print(f"\nФайл уже существует: {pdf_path.name}")
            print("1. Перезаписать")
            print("2. Добавить порядковый номер")
            print("3. Пропустить файл")
            print("4. Перезаписать все совпадения")
            print("5. Добавлять номер для всех совпадений")
            print("6. Пропускать все совпадения")
            choice = input_choice_with_default("Выберите действие [5]: ", {"1", "2", "3", "4", "5", "6"}, "5")
            action = {"1": "overwrite", "2": "number", "3": "skip", "4": "overwrite", "5": "number", "6": "skip"}[choice]
            if choice in {"4", "5", "6"}:
                action_all = action
    if action == "skip":
        return None, None, action_all
    if action == "overwrite":
        return html_path, pdf_path, action_all
    new_html, new_pdf = numbered_paths(html_path, pdf_path)
    return new_html, new_pdf, action_all


def numbered_paths(html_path: Path, pdf_path: Path) -> tuple[Path, Path]:
    stem = html_path.stem
    for counter in range(1, 10_000):
        new_html = html_path.with_name(f"{stem}_{counter}.html")
        new_pdf = pdf_path.with_name(f"{stem}_{counter}.pdf")
        if not new_html.exists() and not new_pdf.exists():
            return new_html, new_pdf
    raise RuntimeError("Не удалось подобрать свободное имя файла.")


def sanitize_filename(value: str) -> str:
    value = BAD_FILENAME_CHARS_RE.sub("_", value).strip().strip(".")
    value = re.sub(r"\s+", "_", value)
    return value[:160]


def choose_name_column(headers: list[str], config: dict[str, Any], interactive: bool) -> str | None:
    saved = config.get("filename_column")
    if saved in headers:
        return saved
    likely = ["receipt_number", "номер чека", "чек", "номер", "number", "id"]
    header_map = {normalize_name(header): header for header in headers}
    for item in likely:
        if item in header_map:
            return header_map[item]
    if not interactive:
        return None
    print("\nВыберите колонку для имени PDF или нажмите Enter для номера строки:")
    print_columns(headers)
    raw = input("Номер колонки: ").strip()
    if not raw:
        return None
    return headers[int(raw) - 1]


def make_record_label(row: dict[str, str], row_idx: int, name_column: str | None) -> str:
    if name_column and row.get(name_column):
        return row[name_column]
    return f"row_{row_idx + 1}"


def print_csv_preview(csv_data: CsvData, config: dict[str, Any]) -> None:
    print(f"\nCSV: {csv_data.path.name}")
    print(f"Кодировка: {csv_data.encoding}, разделитель: {repr(csv_data.delimiter)}, строк: {len(csv_data.rows)}")
    preview_columns = auto_preview_columns(csv_data.headers)
    if not preview_columns:
        print("Выберите колонки для предварительного просмотра.")
        print_columns(csv_data.headers)
        raw = input("Номера колонок через запятую: ").strip()
        preview_columns = [csv_data.headers[int(i) - 1] for i in raw.split(",") if i.strip().isdigit()]
    print_table(csv_data.rows[:10], preview_columns)


def auto_preview_columns(headers: list[str]) -> list[str]:
    keywords = (
        "receipt",
        "номер",
        "date",
        "дата",
        "customer",
        "покупатель",
        "клиент",
        "total",
        "сумма",
    )
    selected = [header for header in headers if any(keyword in normalize_name(header) for keyword in keywords)]
    return (selected or headers[:5])[:5]


def print_table(rows: list[dict[str, str]], columns: list[str]) -> None:
    headers = ["№", *columns]
    table_rows = [[str(i), *(row.get(col, "") for col in columns)] for i, row in enumerate(rows, start=1)]
    widths = [min(max(len(str(cell)) for cell in [header, *(r[idx] for r in table_rows)]), 28) for idx, header in enumerate(headers)]
    print("  ".join(header.ljust(widths[idx]) for idx, header in enumerate(headers)))
    for row in table_rows:
        print("  ".join(truncate(row[idx], widths[idx]).ljust(widths[idx]) for idx in range(len(headers))))


def truncate(value: str, width: int) -> str:
    return value if len(value) <= width else value[: max(0, width - 1)] + "…"


def choose_output_dir(config: dict[str, Any]) -> Path:
    saved = config.get("output_dir")
    default = Path(saved).expanduser() if saved else DEFAULT_OUTPUT_DIR
    raw = input(f"\nПапка сохранения [{default}]: ").strip()
    return (Path(raw).expanduser() if raw else default).resolve()


def print_confirmation(
    template_path: Path,
    csv_path: Path,
    row_indices: list[int],
    receipt_numbers: list[str],
    output_dir: Path,
) -> None:
    print("\nПодтверждение")
    print(f"Шаблон: {template_path.name}")
    print(f"Источник данных: {csv_path.name}")
    print(f"Выбрано записей: {len(row_indices)}")
    print(f"Номера чеков: {', '.join(receipt_numbers[:20])}{' ...' if len(receipt_numbers) > 20 else ''}")
    print(f"Папка сохранения: {output_dir}")


def print_report(result: GenerationResult, output_dir: Path) -> None:
    print("\nГотово.")
    print(f"Создано PDF: {len(result.pdf_files)}")
    print(f"Создано HTML: {len(result.html_files)}")
    print(f"Ошибок: {len(result.errors)}")
    print(f"Папка: {output_dir}")
    for error in result.errors:
        print(f"- {error}")


def post_generation_menu(result: GenerationResult, output_dir: Path) -> None:
    while True:
        print("\nЧто открыть?")
        print("1. Открыть выбранный PDF")
        print("2. Открыть все созданные PDF")
        print("3. Открыть папку с результатами")
        print("4. Ничего не открывать")
        print("5. Вернуться в главное меню")
        choice = input_choice("Выберите действие: ", {"1", "2", "3", "4", "5"})
        if choice == "1":
            if not result.pdf_files:
                print("PDF-файлы не созданы.")
                continue
            for idx, path in enumerate(result.pdf_files, start=1):
                print(f"{idx}. {path.name}")
            pdf = result.pdf_files[int(input_choice("Номер PDF: ", {str(i) for i in range(1, len(result.pdf_files) + 1)})) - 1]
            open_path(pdf)
        elif choice == "2":
            if len(result.pdf_files) > 5 and not ask_yes_no(f"Открыть {len(result.pdf_files)} PDF? [Да/Нет]: "):
                continue
            for pdf in result.pdf_files:
                open_path(pdf)
        elif choice == "3":
            open_path(output_dir)
        elif choice == "4":
            return
        elif choice == "5":
            return


def auto_open_generation_result(result: GenerationResult, output_dir: Path) -> None:
    if not result.pdf_files:
        return
    if len(result.pdf_files) == 1:
        print(f"Открываю PDF в браузере: {result.pdf_files[0].name}")
        open_pdf_in_browser(result.pdf_files[0])
        return
    print(f"Открываю PDF в браузере: {len(result.pdf_files)} файлов.")
    for pdf_path in result.pdf_files:
        open_pdf_in_browser(pdf_path)


def open_pdf_in_browser(path: Path) -> None:
    try:
        if not webbrowser.open_new_tab(path.resolve().as_uri()):
            raise RuntimeError("браузер не принял запрос на открытие")
    except Exception as exc:
        print(f"PDF не удалось открыть в браузере: {path.name}: {exc}")


def open_path(path: Path) -> None:
    try:
        system = platform.system()
        if system == "Windows":
            try:
                os.startfile(str(path))  # type: ignore[attr-defined]
            except OSError:
                if not webbrowser.open(path.resolve().as_uri()):
                    raise
        elif system == "Darwin":
            subprocess.run(["open", str(path)], check=True)
        else:
            subprocess.run(["xdg-open", str(path)], check=True)
    except Exception as exc:
        print(f"PDF или папку не удалось открыть: {exc}")


def print_file_lists(html_files: list[FileInfo], csv_files: list[FileInfo]) -> None:
    print_file_list("Найденные шаблоны чеков", html_files, "html")
    print_file_list("Найденные CSV-файлы", csv_files, "csv")


def print_file_list(title: str, files: list[FileInfo], kind: str) -> None:
    print(f"\n{title}:")
    if not files:
        print("Не найдено.")
        return
    for idx, item in enumerate(files, start=1):
        print(f"{idx}. {item.path.name}")
        print(f"   Путь: {item.path}")
        print(f"   Изменён: {item.modified}")
        if kind == "csv":
            if item.csv_error:
                print(f"   Ошибка CSV: {item.csv_error}")
            else:
                print(f"   Строк: {item.csv_rows}")
                print(f"   Колонки: {', '.join(item.csv_headers or [])}")
        else:
            print(f"   Плейсхолдеры: {', '.join(item.placeholders or []) or 'не найдены'}")


def choose_from_list(title: str, files: list[FileInfo]) -> FileInfo:
    print_file_list(title, files, "csv" if title.lower().find("csv") >= 0 else "html")
    valid = {str(i) for i in range(1, len(files) + 1)}
    return files[int(input_choice("Выберите номер: ", valid)) - 1]


def print_columns(headers: list[str]) -> None:
    for idx, header in enumerate(headers, start=1):
        print(f"{idx}. {header}")


def choose_column(headers: list[str], prompt: str) -> str:
    valid = {str(i) for i in range(1, len(headers) + 1)}
    return headers[int(input_choice(prompt, valid)) - 1]


def choose_directory_dialog() -> Path | None:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        path = filedialog.askdirectory(title="Выберите директорию для поиска")
        root.destroy()
        return Path(path).resolve() if path else None
    except Exception as exc:
        print(f"Не удалось открыть окно выбора папки: {exc}")
        return None


def print_selected_dirs(directories: list[Path]) -> None:
    if directories:
        print("Выбранные директории:")
        for path in unique_existing_dirs(directories):
            print(f"- {path}")


def unique_existing_dirs(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        resolved = path.expanduser().resolve()
        key = str(resolved).lower()
        if key not in seen and resolved.exists() and resolved.is_dir():
            seen.add(key)
            result.append(resolved)
    return result


def unique_paths(paths: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for path in paths:
        key = path.lower()
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def resolve_config_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = SCRIPT_DIR / path
    return path.resolve()


def input_choice(prompt: str, valid: set[str]) -> str:
    while True:
        value = input(prompt).strip()
        if value in valid:
            return value
        print(f"Введите один из вариантов: {', '.join(sorted(valid))}")


def input_choice_with_default(prompt: str, valid: set[str], default: str) -> str:
    while True:
        value = input(prompt).strip()
        if not value:
            return default
        if value in valid:
            return value
        print(f"Введите один из вариантов: {', '.join(sorted(valid))}")


def ask_yes_no(prompt: str) -> bool:
    while True:
        value = input(prompt).strip().lower()
        if value in {"да", "д", "yes", "y"}:
            return True
        if value in {"нет", "н", "no", "n"}:
            return False
        print("Введите Да или Нет.")


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Предупреждение: receipt_config.json не удалось прочитать: {exc}")
        return {}


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def ensure_existing_file(path: Path, label: str) -> None:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"{label} не найден: {path}")


def format_mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%d.%m.%Y %H:%M:%S")
    except OSError:
        return "неизвестно"


@contextlib.contextmanager
def suppress_native_stderr():
    """Hide noisy GLib-GIO warnings emitted by WeasyPrint native libraries."""
    try:
        stderr_fd = sys.stderr.fileno()
    except Exception:
        yield
        return
    saved_fd = os.dup(stderr_fd)
    try:
        with open(os.devnull, "w") as devnull:
            os.dup2(devnull.fileno(), stderr_fd)
            yield
    finally:
        os.dup2(saved_fd, stderr_fd)
        os.close(saved_fd)


if __name__ == "__main__":
    main()
