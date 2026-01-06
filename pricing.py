import datetime as dt
import email.message
import json
import os
import re
import sqlite3
import smtplib
import urllib.error
import urllib.request
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas


DEFAULTS = {
    "labor_rate": 15.00,
    "markup_pct": 0.30,
    "vat_pct": 0.20,
    "currency": "GBP",
    "bom_api_url": "http://localhost:8000",
    "materials_db_path": os.path.join("Context", "materials.sqlite"),
    "template_path": os.path.join("Context", "quote_template.md"),
    "output_dir": "out",
    "quote_valid_days": 14,
}

_MONGO_CLIENT = None


def load_dotenv(path=".env"):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key:
                os.environ[key] = value


load_dotenv()


def env_float(name, default):
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    try:
        return float(val)
    except ValueError:
        raise ValueError(f"{name} must be a number")


def env_int(name, default):
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    try:
        return int(val)
    except ValueError:
        raise ValueError(f"{name} must be an integer")


def env_str(name, default):
    val = os.environ.get(name)
    return default if val is None or val == "" else val


def parse_pct(value):
    if value <= 1:
        return value
    return value / 100.0


def get_defaults():
    return {
        "labor_rate": env_float("LABOR_RATE", DEFAULTS["labor_rate"]),
        "markup_pct": parse_pct(env_float("MARKUP_PCT", DEFAULTS["markup_pct"] * 100)),
        "vat_pct": parse_pct(env_float("VAT_PCT", DEFAULTS["vat_pct"] * 100)),
        "currency": env_str("CURRENCY", DEFAULTS["currency"]),
        "bom_api_url": env_str("BOM_API_URL", DEFAULTS["bom_api_url"]),
        "materials_db_path": env_str("MATERIALS_DB_PATH", DEFAULTS["materials_db_path"]),
        "template_path": env_str("TEMPLATE_PATH", DEFAULTS["template_path"]),
        "output_dir": env_str("OUTPUT_DIR", DEFAULTS["output_dir"]),
        "quote_valid_days": env_int("QUOTE_VALID_DAYS", DEFAULTS["quote_valid_days"]),
        "sender_name": env_str("SENDER_NAME", "Bakery Nation"),
    }


def load_fx_rates():
    if os.environ.get("FX_LIVE", "").lower() in ("1", "true", "yes", "on"):
        base = env_str("FX_BASE", DEFAULTS["currency"]).upper()
        api_url = env_str("FX_API_URL", f"https://open.er-api.com/v6/latest/{base}")
        cache_seconds = env_int("FX_CACHE_SECONDS", 3600)
        cache_dir = env_str("OUTPUT_DIR", DEFAULTS["output_dir"])
        cache_path = os.path.join(cache_dir, "fx_cache.json")
        cached = load_fx_cache(cache_path, base, cache_seconds)
        if cached:
            print(f"[fx] using cached rates from {cache_path} (base {base})")
            return cached
        rates = fetch_fx_rates(api_url, base)
        if rates:
            save_fx_cache(cache_path, base, rates)
            print(f"[fx] fetched live rates from {api_url} (base {base})")
            return rates
    raw = os.environ.get("FX_RATES_JSON", "").strip()
    if not raw:
        print("[fx] no rates configured; FX conversion disabled")
        return {}
    try:
        data = json.loads(raw)
        rates = {k.upper(): float(v) for k, v in data.items()}
        print("[fx] using rates from FX_RATES_JSON")
        return rates
    except (ValueError, TypeError, json.JSONDecodeError):
        raise ValueError("FX_RATES_JSON must be valid JSON mapping currency -> rate")


def load_fx_cache(path, base, max_age_seconds):
    if not path or max_age_seconds <= 0 or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if payload.get("base", "").upper() != base:
            return None
        timestamp = int(payload.get("timestamp", 0))
        if (dt.datetime.utcnow().timestamp() - timestamp) > max_age_seconds:
            return None
        rates = payload.get("rates", {})
        return {k.upper(): float(v) for k, v in rates.items()}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def save_fx_cache(path, base, rates):
    if not path:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {
        "base": base,
        "timestamp": int(dt.datetime.utcnow().timestamp()),
        "rates": rates,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def fetch_fx_rates(api_url, base):
    try:
        with urllib.request.urlopen(api_url, timeout=8) as resp:
            payload = resp.read().decode("utf-8")
        data = json.loads(payload)
        rates = data.get("rates") or {}
        if not isinstance(rates, dict):
            return {}
        rates = {k.upper(): float(v) for k, v in rates.items()}
        if base not in rates:
            rates[base] = 1.0
        return rates
    except Exception:
        return {}


def convert_currency(amount, from_currency, to_currency, rates):
    from_cur = from_currency.upper()
    to_cur = to_currency.upper()
    if from_cur == to_cur:
        return amount
    if from_cur not in rates or to_cur not in rates:
        raise ValueError(f"Missing FX rate for {from_cur} or {to_cur}")
    return amount * (rates[to_cur] / rates[from_cur])


def smtp_settings():
    host = os.environ.get("SMTP_HOST", "").strip()
    if not host:
        return None
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASS", "").strip()
    sender = os.environ.get("SMTP_FROM", "").strip() or user
    use_tls = os.environ.get("SMTP_TLS", "true").lower() in ("1", "true", "yes")
    use_ssl = os.environ.get("SMTP_SSL", "false").lower() in ("1", "true", "yes")
    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "sender": sender,
        "use_tls": use_tls,
        "use_ssl": use_ssl,
    }


def sheets_settings():
    sheet_id = os.environ.get("SHEET_ID", "").strip()
    if not sheet_id:
        return None
    tab = os.environ.get("SHEET_TAB", "Sheet1").strip() or "Sheet1"
    creds_path = os.environ.get("SHEETS_CREDENTIALS_PATH", "").strip()
    if not creds_path:
        creds_path = os.environ.get("GOOGLE_SA_PATH", "").strip()
    if not creds_path:
        return None
    return {"sheet_id": sheet_id, "tab": tab, "creds_path": creds_path}


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


def mongo_settings():
    uri = os.environ.get("MONGODB_URI", "").strip()
    if not uri:
        return None
    return {
        "uri": uri,
        "db": os.environ.get("MONGODB_DB", "bakery").strip() or "bakery",
        "collection": os.environ.get("MONGODB_MATERIALS_COLLECTION", "materials").strip()
        or "materials",
    }


def mongo_collection():
    settings = mongo_settings()
    if not settings:
        return None
    global _MONGO_CLIENT
    if _MONGO_CLIENT is None:
        try:
            from pymongo import MongoClient
        except ImportError as exc:
            raise RuntimeError("pymongo is required when MONGODB_URI is set") from exc
        _MONGO_CLIENT = MongoClient(settings["uri"])
    return _MONGO_CLIENT[settings["db"]][settings["collection"]]


def load_material_costs(db_path, names):
    if not names:
        return {}
    coll = mongo_collection()
    if coll is not None:
        docs = coll.find({"name": {"$in": list(names)}})
        return {
            doc["name"]: {
                "name": doc["name"],
                "unit": doc["unit"],
                "unit_cost": doc["unit_cost"],
                "currency": doc["currency"],
            }
            for doc in docs
        }
    placeholders = ",".join("?" for _ in names)
    query = f"SELECT name, unit, unit_cost, currency FROM materials WHERE name IN ({placeholders})"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, list(names)).fetchall()
    return {row["name"]: dict(row) for row in rows}


def list_materials(db_path):
    coll = mongo_collection()
    if coll is not None:
        docs = coll.find().sort("name", 1)
        return [
            {
                "name": doc["name"],
                "unit": doc["unit"],
                "unit_cost": doc["unit_cost"],
                "currency": doc["currency"],
            }
            for doc in docs
        ]
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT name, unit, unit_cost, currency FROM materials ORDER BY name").fetchall()
    return [dict(row) for row in rows]


def get_material(db_path, name):
    coll = mongo_collection()
    if coll is not None:
        doc = coll.find_one({"name": name})
        if not doc:
            return None
        return {
            "name": doc["name"],
            "unit": doc["unit"],
            "unit_cost": doc["unit_cost"],
            "currency": doc["currency"],
        }
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT name, unit, unit_cost, currency FROM materials WHERE name = ?",
            (name,),
        ).fetchone()
    return dict(row) if row else None


def update_material_cost(db_path, name, unit_cost):
    coll = mongo_collection()
    if coll is not None:
        result = coll.update_one({"name": name}, {"$set": {"unit_cost": unit_cost}})
        if result.matched_count == 0:
            raise ValueError("Material not found")
        return
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE materials SET unit_cost = ? WHERE name = ?",
            (unit_cost, name),
        )
        conn.commit()


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


def markdown_to_text(markdown_text):
    lines = []
    for raw in markdown_text.splitlines():
        line = raw.strip()
        if line.startswith("|") and line.endswith("|"):
            parts = [p.strip() for p in line.strip("|").split("|")]
            if all(set(p) <= {"-"} or p == "" for p in parts):
                continue
            lines.append(" | ".join(parts))
            continue
        line = line.replace("**", "")
        line = re.sub(r"^#+\s*", "", line)
        lines.append(line)
    return "\n".join(lines).strip() + "\n"


def write_text_version(markdown_text, out_md_path):
    base = os.path.splitext(out_md_path)[0]
    out_txt = f"{base}.txt"
    text = markdown_to_text(markdown_text)
    with open(out_txt, "w", encoding="utf-8") as f:
        f.write(text)
    return out_txt


def write_pdf_version(out_md_path, data, lines):
    base = os.path.splitext(out_md_path)[0]
    out_pdf = f"{base}.pdf"
    c = canvas.Canvas(out_pdf, pagesize=A4)
    width, height = A4
    margin_x = 50
    y = height - 60
    line_height = 14
    max_width = width - (margin_x * 2)

    def draw_line(line, y_pos, font="Helvetica", size=11):
        c.setFont(font, size)
        if not line:
            c.drawString(x, y_pos, "")
            return y_pos - line_height
        words = line.split(" ")
        current = []
        for word in words:
            trial = " ".join(current + [word])
            if pdfmetrics.stringWidth(trial, font, size) <= max_width:
                current.append(word)
            else:
                c.drawString(margin_x, y_pos, " ".join(current))
                y_pos -= line_height
                current = [word]
        if current:
            c.drawString(margin_x, y_pos, " ".join(current))
            y_pos -= line_height
        return y_pos

    def ensure_space(y_pos, needed=20):
        if y_pos <= 60 + needed:
            c.showPage()
            return height - 60
        return y_pos

    x = margin_x
    c.setFont("Helvetica-Bold", 18)
    c.drawString(x, y, f"{data['company_name']} — Quotation")
    y -= 28

    c.setFont("Helvetica", 11)
    meta_lines = [
        f"Quote ID: {data['quote_id']}",
        f"Date: {data['quote_date']}",
        f"Valid Until: {data['valid_until']}",
        f"Customer: {data['customer_name']}",
        f"Project: {data['job_type']} × {data['quantity']}",
        f"Delivery / Due: {data['due_date']}",
    ]
    for line in meta_lines:
        y = ensure_space(y, 16)
        c.drawString(x, y, line)
        y -= 16

    y -= 8
    y = ensure_space(y, 24)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x, y, "Bill of Materials & Labor")
    y -= 18

    col_x = [x, x + 220, x + 280, x + 360, x + 460]
    c.setFont("Helvetica-Bold", 10)
    c.drawString(col_x[0], y, "Item")
    c.drawString(col_x[1], y, "Qty")
    c.drawString(col_x[2], y, "Unit")
    c.drawString(col_x[3], y, f"Unit Cost ({data['currency']})")
    c.drawString(col_x[4], y, "Line Cost")
    y -= 8
    c.line(x, y, width - margin_x, y)
    y -= 12

    c.setFont("Helvetica", 10)
    for row in lines:
        y = ensure_space(y, 16)
        c.drawString(col_x[0], y, str(row["name"]))
        c.drawRightString(col_x[1] + 40, y, str(row["qty"]))
        c.drawString(col_x[2], y, str(row["unit"]))
        c.drawRightString(col_x[3] + 70, y, str(row["unit_cost"]))
        c.drawRightString(col_x[4] + 50, y, str(row["line_cost"]))
        y -= 14

    y = ensure_space(y, 18)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(col_x[0], y, f"Labor (@ {data['labor_rate']}/h)")
    c.drawRightString(col_x[1] + 40, y, str(data["labor_hours"]))
    c.drawString(col_x[2], y, "h")
    c.drawRightString(col_x[4] + 50, y, str(data["labor_cost"]))
    y -= 20

    c.setFont("Helvetica", 11)
    totals = [
        ("Materials Subtotal", data["materials_subtotal"]),
        ("Labor Subtotal", data["labor_cost"]),
        ("Subtotal (pre-markup)", data["subtotal"]),
        (f"Markup ({data['markup_pct']})", data["markup_value"]),
        ("Price before VAT", data["price_before_vat"]),
        (f"VAT ({data['vat_pct']})", data["vat_value"]),
        ("Total", data["total"]),
    ]
    for label, value in totals:
        y = ensure_space(y, 16)
        c.drawString(x, y, f"{label}: {value} {data['currency']}")
        y -= 16

    y -= 6
    y = ensure_space(y, 30)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x, y, "Notes:")
    y -= 16
    c.setFont("Helvetica", 11)
    y = draw_line(data["notes"], y)
    y -= 8

    c.setFont("Helvetica-Oblique", 10)
    y = ensure_space(y, 14)
    c.drawString(x, y, "Thank you for your business!")

    c.save()
    return out_pdf


def send_quote_email(settings, recipient, subject, body, attachments):
    if not settings or not settings.get("sender"):
        raise ValueError("SMTP settings are missing or incomplete")

    msg = email.message.EmailMessage()
    msg["From"] = settings["sender"]
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(body)

    for path in attachments:
        with open(path, "rb") as f:
            data = f.read()
        filename = os.path.basename(path)
        maintype = "text"
        subtype = "plain"
        if filename.endswith(".md"):
            subtype = "markdown"
        if filename.endswith(".pdf"):
            maintype = "application"
            subtype = "pdf"
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)

    if settings["use_ssl"]:
        server = smtplib.SMTP_SSL(settings["host"], settings["port"])
    else:
        server = smtplib.SMTP(settings["host"], settings["port"])
    with server:
        if settings["use_tls"] and not settings["use_ssl"]:
            server.starttls()
        if settings["user"] and settings["password"]:
            server.login(settings["user"], settings["password"])
        server.send_message(msg)


def append_quote_to_sheet(settings, headers, row):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    if not os.path.exists(settings["creds_path"]):
        raise ValueError("Service account JSON not found")

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = service_account.Credentials.from_service_account_file(
        settings["creds_path"], scopes=scopes
    )
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sheet_id = settings["sheet_id"]
    tab = settings["tab"]

    safe_tab = f"'{tab}'" if " " in tab else tab
    existing = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=sheet_id, range=f"{safe_tab}!1:1")
        .execute()
    )
    if not existing.get("values"):
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range=f"{safe_tab}!1:1",
            valueInputOption="USER_ENTERED",
            body={"values": [headers]},
        ).execute()

    service.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range=f"{safe_tab}!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()


def compute_costs(inputs, defaults):
    fx_rates = load_fx_rates()
    estimate = bom_estimate(defaults["bom_api_url"], inputs["job_type"], inputs["quantity"])
    materials = estimate["materials"]
    labor_hours = float(estimate["labor_hours"])

    material_names = [m["name"] for m in materials]
    costs = load_material_costs(defaults["materials_db_path"], material_names)
    missing = [name for name in material_names if name not in costs]
    if missing:
        raise ValueError(f"Missing materials in DB: {', '.join(missing)}")

    lines = []
    materials_subtotal = 0.0
    for m in materials:
        info = costs[m["name"]]
        unit_cost = float(info["unit_cost"])
        if info["currency"] != inputs["currency"]:
            try:
                unit_cost = convert_currency(unit_cost, info["currency"], inputs["currency"], fx_rates)
            except ValueError as exc:
                inputs.setdefault("warnings", []).append(
                    f"{m['name']} priced in {info['currency']} but quote currency is {inputs['currency']}: {exc}"
                )
        per_unit_cost = unit_cost_for_bom(unit_cost, m["unit"], info["unit"])
        line_cost = m["qty"] * per_unit_cost
        materials_subtotal += line_cost
        lines.append(
            {
                "name": m["name"],
                "qty": m["qty"],
                "unit": m["unit"],
                "unit_cost": fmt_money(per_unit_cost),
                "line_cost": fmt_money(line_cost),
            }
        )

    base_currency = defaults["currency"]
    if inputs["currency"] != base_currency:
        try:
            inputs["labor_rate"] = convert_currency(
                float(inputs["labor_rate"]),
                base_currency,
                inputs["currency"],
                fx_rates,
            )
        except ValueError as exc:
            inputs.setdefault("warnings", []).append(
                f"Labor rate in {base_currency} but quote currency is {inputs['currency']}: {exc}"
            )
    labor_cost = labor_hours * inputs["labor_rate"]
    subtotal = materials_subtotal + labor_cost
    markup_value = subtotal * inputs["markup_pct"]
    price_before_vat = subtotal + markup_value
    vat_value = price_before_vat * inputs["vat_pct"]
    total = price_before_vat + vat_value
    unit_price = total / inputs["quantity"] if inputs["quantity"] else 0

    summary = {
        "materials_subtotal": fmt_money(materials_subtotal),
        "labor_cost": fmt_money(labor_cost),
        "labor_hours": labor_hours,
        "subtotal": fmt_money(subtotal),
        "markup_value": fmt_money(markup_value),
        "price_before_vat": fmt_money(price_before_vat),
        "vat_value": fmt_money(vat_value),
        "total": fmt_money(total),
        "unit_price": fmt_money(unit_price),
    }
    return lines, summary


def build_quote(inputs, defaults, lines=None, summary=None):
    if lines is None or summary is None:
        lines, summary = compute_costs(inputs, defaults)

    quote_date = dt.date.today()
    valid_until = quote_date + dt.timedelta(days=defaults["quote_valid_days"])
    quote_id = f"Q-{quote_date.strftime('%Y%m%d')}-{inputs['quantity']:03d}"

    with open(defaults["template_path"], "r", encoding="utf-8") as f:
        template_text = f.read()

    data = {
        "company_name": inputs["company_name"],
        "quote_id": quote_id,
        "quote_date": quote_date.isoformat(),
        "valid_until": valid_until.isoformat(),
        "customer_name": inputs["customer_name"],
        "job_type": inputs["job_type"],
        "quantity": inputs["quantity"],
        "due_date": inputs["due_date"],
        "currency": inputs["currency"],
        "lines": lines,
        "labor_rate": fmt_money(inputs["labor_rate"]),
        "labor_hours": summary["labor_hours"],
        "labor_cost": summary["labor_cost"],
        "materials_subtotal": summary["materials_subtotal"],
        "subtotal": summary["subtotal"],
        "markup_pct": f"{inputs['markup_pct']*100:.0f}%",
        "markup_value": summary["markup_value"],
        "price_before_vat": summary["price_before_vat"],
        "vat_pct": f"{inputs['vat_pct']*100:.0f}%",
        "vat_value": summary["vat_value"],
        "total": summary["total"],
        "notes": f"{inputs['notes']} (Customer email: {inputs['customer_email']})",
    }

    rendered = render_template(template_text, data)
    os.makedirs(defaults["output_dir"], exist_ok=True)
    out_path = os.path.join(defaults["output_dir"], f"quote_{quote_id}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(rendered)
    out_txt_path = write_text_version(rendered, out_path)
    out_pdf_path = write_pdf_version(out_path, data, lines)

    return {
        "quote_id": quote_id,
        "quote_date": quote_date.isoformat(),
        "valid_until": valid_until.isoformat(),
        "out_path": out_path,
        "out_txt_path": out_txt_path,
        "out_pdf_path": out_pdf_path,
        "markdown": rendered,
        "lines": lines,
        "summary": summary,
        "warnings": inputs.get("warnings", []),
    }
