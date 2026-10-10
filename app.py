from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path

from flask import Flask, render_template_string, request, send_file
from weasyprint import HTML

from receipt_generator import PRINT_CSS, inject_print_css, render_template


BASE_DIR = Path(__file__).resolve().parent
RECEIPT_TEMPLATE = (BASE_DIR / "receipt_template.html").read_text(encoding="utf-8")
FIELDS = ("receipt_number", "date", "customer", "product", "quantity", "price", "total")

app = Flask(__name__)

FORM = """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Генератор чеков PDF</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; font: 16px/1.45 system-ui, sans-serif; background: #f3f4f6; color: #111827; }
    main { width: min(760px, calc(100% - 32px)); margin: 48px auto; background: white; padding: 32px; border-radius: 20px; box-shadow: 0 20px 50px #11182718; }
    h1 { margin: 0 0 8px; }
    p { margin: 0 0 24px; color: #4b5563; }
    form { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    label { display: grid; gap: 6px; font-weight: 650; }
    .wide { grid-column: 1 / -1; }
    input { width: 100%; border: 1px solid #d1d5db; border-radius: 10px; padding: 11px 12px; font: inherit; }
    button { grid-column: 1 / -1; border: 0; border-radius: 10px; padding: 13px 18px; background: #2563eb; color: white; font: inherit; font-weight: 700; cursor: pointer; }
    @media (max-width: 620px) { form { grid-template-columns: 1fr; } .wide { grid-column: auto; } }
  </style>
</head>
<body>
  <main>
    <h1>Генератор чеков PDF</h1>
    <p>Заполните реквизиты и скачайте готовый товарный чек.</p>
    <form method="post" action="/generate">
      <label>Номер чека<input name="receipt_number" value="000149" required></label>
      <label>Дата<input name="date" type="date" value="{{ today }}" required></label>
      <label class="wide">Покупатель<input name="customer" value="ООО Пример" required></label>
      <label class="wide">Товар<input name="product" value="Консультационные услуги" required></label>
      <label>Количество<input name="quantity" type="number" min="1" value="1" required></label>
      <label>Цена<input name="price" value="15 000,00" required></label>
      <label class="wide">Итого<input name="total" value="15 000,00" required></label>
      <button type="submit">Сформировать PDF</button>
    </form>
  </main>
</body>
</html>
"""


@app.get("/")
def index():
    return render_template_string(FORM, today=date.today().isoformat())


@app.post("/generate")
def generate():
    record = {field: request.form.get(field, "").strip() for field in FIELDS}
    mapping = {field: field for field in FIELDS}
    printable = inject_print_css(RECEIPT_TEMPLATE, PRINT_CSS)
    rendered = render_template(printable, record, mapping, {})
    output = BytesIO()
    HTML(string=rendered, base_url=str(BASE_DIR)).write_pdf(output)
    output.seek(0)
    safe_number = "".join(ch for ch in record["receipt_number"] if ch.isalnum() or ch in "-_") or "receipt"
    return send_file(output, mimetype="application/pdf", as_attachment=True, download_name=f"receipt_{safe_number}.pdf")


@app.get("/health")
def health():
    return {"application": "pdf-receipt-generator", "status": "healthy"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
