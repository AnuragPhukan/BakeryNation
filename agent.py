import datetime as dt
import sys

from pricing import build_quote, compute_costs, fetch_job_types, get_defaults, parse_pct


def prompt(text, default=None, validator=None):
    suffix = f" [{default}]" if default is not None else ""
    while True:
        raw = input(f"{text}{suffix}: ").strip()
        if raw == "" and default is not None:
            raw = str(default)
        if validator is None:
            return raw
        try:
            return validator(raw)
        except ValueError as exc:
            print(f"Invalid value: {exc}")


def fetch_job_types(api_url):
    url = f"{api_url.rstrip('/')}/job-types"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            payload = resp.read().decode("utf-8")
            data = json.loads(payload)
        return data
    except Exception:
        return None


def bom_estimate(api_url, job_type, quantity):
    url = f"{api_url.rstrip('/')}/estimate"
    data = json.dumps({"job_type": job_type, "quantity": quantity}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = resp.read().decode("utf-8")
            return json.loads(payload)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8")
        raise RuntimeError(f"BOM API error {exc.code}: {detail}")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot reach BOM API at {url}: {exc}")


def load_material_costs(db_path, names):
    if not names:
        return {}
    placeholders = ",".join("?" for _ in names)
    query = f"SELECT name, unit, unit_cost, currency FROM materials WHERE name IN ({placeholders})"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, list(names)).fetchall()
    return {row["name"]: dict(row) for row in rows}


def convert_qty(qty, from_unit, to_unit):
    if from_unit == to_unit:
        return qty
    if from_unit == "g" and to_unit == "kg":
        return qty * 0.001
    if from_unit == "kg" and to_unit == "g":
        return qty * 1000
    if from_unit == "ml" and to_unit == "L":
        return qty / 1000.0
    if from_unit == "L" and to_unit == "ml":
        return qty * 1000.0
    raise ValueError(f"Cannot convert {from_unit} to {to_unit}")


def unit_cost_for_bom(unit_cost_db, bom_unit, db_unit):
    factor = convert_qty(1, bom_unit, db_unit)
    return unit_cost_db * factor


def render_template(template_text, data):
    section_pattern = re.compile(r"{{#lines}}(.*?){{/lines}}", re.S)

    def replace_vars(text, context):
        for key, value in context.items():
            text = text.replace(f"{{{{{key}}}}}", str(value))
        return text

    def render_section(match):
        block = match.group(1)
        lines_out = []
        for line in data.get("lines", []):
            merged = {**data, **line}
            lines_out.append(replace_vars(block, merged))
        return "".join(lines_out)

    rendered = section_pattern.sub(render_section, template_text)
    rendered = replace_vars(rendered, data)
    return rendered


def fmt_money(value):
    return f"{value:.2f}"


def main():
    defaults = get_defaults()
    print("Bakery Quotation Agent")
    job_types = fetch_job_types(defaults["bom_api_url"]) or ["cupcakes", "cake", "pastry_box"]

    def valid_job(val):
        if val not in job_types:
            raise ValueError(f"must be one of {', '.join(job_types)}")
        return val

    def valid_qty(val):
        q = int(val)
        if q <= 0:
            raise ValueError("quantity must be > 0")
        return q

    job_type = prompt("Job type", job_types[0], valid_job)
    quantity = prompt("Quantity", 1, valid_qty)
    due_date = prompt("Due date (e.g., 2025-10-01)", dt.date.today().isoformat())
    company_name = prompt("Your company name", "Bakery Co.")
    customer_name = prompt("Customer name/company", "Customer")
    customer_email = prompt("Customer email", "customer@example.com")
    currency = prompt("Currency", defaults["currency"])
    labor_rate = float(prompt("Labor rate per hour", defaults["labor_rate"]))
    markup_pct = parse_pct(float(prompt("Markup %", defaults["markup_pct"] * 100)))
    vat_pct = parse_pct(float(prompt("VAT %", defaults["vat_pct"] * 100)))
    notes = prompt("Notes", "Please confirm delivery details.")

    inputs = {
        "job_type": job_type,
        "quantity": quantity,
        "due_date": due_date,
        "company_name": company_name,
        "customer_name": customer_name,
        "customer_email": customer_email,
        "currency": currency,
        "labor_rate": labor_rate,
        "markup_pct": markup_pct,
        "vat_pct": vat_pct,
        "notes": notes,
    }

    try:
        lines, summary = compute_costs(inputs, defaults)
    except ValueError as exc:
        print(str(exc))
        print("Please add missing materials and retry.")
        sys.exit(1)

    print("\nQuote summary (pre-generation)")
    print(f"- Materials subtotal: {summary['materials_subtotal']} {currency}")
    print(f"- Labor cost: {summary['labor_cost']} {currency}")
    print(f"- Subtotal: {summary['subtotal']} {currency}")
    print(f"- Markup ({markup_pct*100:.0f}%): {summary['markup_value']} {currency}")
    print(f"- Price before VAT: {summary['price_before_vat']} {currency}")
    print(f"- VAT ({vat_pct*100:.0f}%): {summary['vat_value']} {currency}")
    print(f"- Total: {summary['total']} {currency}")
    print(f"- Unit price: {summary['unit_price']} {currency}")

    if inputs.get("warnings"):
        for warning in inputs["warnings"]:
            print(f"Warning: {warning}")

    result = build_quote(inputs, defaults, lines=lines, summary=summary)
    print(f"\nQuote saved to {result['out_path']}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
