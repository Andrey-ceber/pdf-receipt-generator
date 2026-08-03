# Генератор чеков PDF

Скрипт `receipt_generator.py` формирует отдельные HTML и PDF чеки из HTML-шаблона и CSV-файла. Данные CSV подставляются в плейсхолдеры вида `{{receipt_number}}`.

## Установка на Windows

1. Установите Python 3.10 или новее.
2. Создайте виртуальное окружение:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

3. Установите зависимости:

```powershell
python -m pip install -r requirements.txt
```

4. Проверьте WeasyPrint:

```powershell
python -m weasyprint --info
```

Если WeasyPrint не запускается из-за системных библиотек, используйте официальный установщик WeasyPrint для Windows или WSL. Для работы именно этого скрипта как Python-библиотеки нужен импорт пакета `weasyprint` в активном окружении.

5. Запустите интерактивный режим:

```powershell
python receipt_generator.py
```

## Установка на macOS

1. Установите Python 3.10 или новее.
2. Создайте виртуальное окружение:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. Установите зависимости:

```bash
python -m pip install -r requirements.txt
```

4. Если установка через pip не подхватила системные библиотеки, установите WeasyPrint через Homebrew:

```bash
brew install weasyprint
```

5. Проверьте WeasyPrint:

```bash
python -m weasyprint --info
```

6. Запустите интерактивный режим:

```bash
python receipt_generator.py
```

## Примеры запуска

Интерактивный запуск:

```bash
python receipt_generator.py
```

Одна строка CSV:

```bash
python receipt_generator.py --template "receipt_template.html" --data "checks.csv" --row 2
```

Несколько строк и диапазон:

```bash
python receipt_generator.py --template "receipt_template.html" --data "checks.csv" --rows "1,3,5-10"
```

Все строки:

```bash
python receipt_generator.py --template "receipt_template.html" --data "checks.csv" --all
```

Папка вывода:

```bash
python receipt_generator.py --template "receipt_template.html" --data "checks.csv" --all --output "output"
```

## Шаблоны и плейсхолдеры

HTML-шаблоны можно хранить рядом со скриптом или в любых других папках. При интерактивном запуске скрипт умеет искать `.html`, `.htm` и `.csv` рекурсивно в выбранных директориях.

Плейсхолдеры пишутся в HTML так:

```html
{{receipt_number}}
{{date}}
{{customer}}
{{product}}
{{quantity}}
{{price}}
{{total}}
```

Скрипт автоматически сопоставляет плейсхолдеры с одноимёнными колонками CSV без учёта регистра и лишних пробелов. Для несопоставленных полей можно выбрать колонку, задать постоянное значение, оставить пустым или отменить генерацию.

## Шрифты

Если нужен конкретный шрифт с кириллицей, создайте папку `fonts` рядом со скриптом и положите туда файл `.ttf`, `.otf` или `.ttc`, например:

```text
fonts/Roboto-Regular.ttf
```

Скрипт сначала ищет шрифты в этой папке, затем среди системных шрифтов Windows или macOS. Предпочтение отдаётся Roboto, затем Liberation Sans и DejaVu Sans.

## Файлы настроек

`receipt_config.json` хранит последние директории, выбранный шаблон, CSV, папку вывода, сопоставления плейсхолдеров и колонку для имени PDF. При следующем запуске скрипт предложит повторить предыдущую настройку.
