# Bakery Quotation Agent

Small CLI agent that gathers job details, calls the BOM API, prices materials from SQLite, applies markup/VAT, and generates a ready-to-send quote.

## Prerequisites

- Python 3
- Docker + docker compose (for the BOM API)
- `python-multipart` (installed via `requirements.txt`) for FastAPI form handling in the UI

## Run

1) Start the BOM API:

```bash
docker compose up --build
```

2) Run the agent:

```bash
python3 agent.py
```

The quote is saved to `out/quote_<id>.md`.
The agent also generates `out/quote_<id>.txt` and `out/quote_<id>.pdf`.

## Render (single service)

Render exposes one port per service. Use the bundled proxy/manager to run both the BOM API and UI behind a single service.

Start command:

```bash
python3 render_start.py
```

The proxy listens on `$PORT`, routes `/api/*` and `/estimate`/`/job-types` to the BOM API, and everything else to the UI. Override ports with `BOM_PORT`/`UI_PORT` if needed.

## UI (optional)

Start the BOM API, then run:

```bash
python3 -m uvicorn ui:app --reload --port 8080
```

Open `http://localhost:8080` to fill out a form and download the generated quote.

## Chat UI (Mistral)

Provide your Mistral API key in `.env`:

```
MISTRAL_API_KEY=your_mistral_key
MISTRAL_BASE_URL=https://codestral.mistral.ai/v1
MISTRAL_MODEL=mistral-large-latest
```

Then run:

```bash
python3 -m uvicorn ui:app --reload --port 8080
```

Open `http://localhost:8080/chat`.

## Configuration

Defaults are baked in, but you can override with environment variables:

- `BOM_API_URL` (default `http://localhost:8000`)
- `MATERIALS_DB_PATH` (default `Context/materials.sqlite`)
- `TEMPLATE_PATH` (default `Context/quote_template.md`)
- `OUTPUT_DIR` (default `out`)
- `LABOR_RATE` (default `15.00`)
- `MARKUP_PCT` (default `30` or `0.30`)
- `VAT_PCT` (default `20` or `0.20`)
- `CURRENCY` (default `GBP`)
- `QUOTE_VALID_DAYS` (default `14`)
- `FX_RATES_JSON` (optional JSON mapping like `{"GBP":1,"USD":1.27,"EUR":1.17}`)
- `WORLD_TIME_API_URL` (optional, defaults to London time via WorldTimeAPI)
- `SENDER_NAME` (optional, used for email sign-off; default `Bakery Nation`)
- `MONGODB_URI` (optional; when set, materials are read from MongoDB instead of SQLite)
- `MONGODB_DB` (default `bakery`)
- `MONGODB_MATERIALS_COLLECTION` (default `materials`)

Example:

```bash
LABOR_RATE=18 MARKUP_PCT=35 VAT_PCT=20 python3 agent.py
```

## Email delivery (optional)

If you want the UI to email the quote to the customer, set SMTP env vars:

- `SMTP_HOST` (required)
- `SMTP_PORT` (default `587`)
- `SMTP_USER`
- `SMTP_PASS`
- `SMTP_FROM` (defaults to `SMTP_USER`)
- `SMTP_TLS` (default `true`)
- `SMTP_SSL` (default `false`)

Example:

```bash
SMTP_HOST=smtp.gmail.com SMTP_PORT=587 SMTP_USER=you@gmail.com SMTP_PASS=app_password SMTP_FROM=you@gmail.com python3 -m uvicorn ui:app --reload --port 8080
```

### Using a .env file

You can place SMTP and config values in a `.env` file in the project root:

```
SMTP_HOST=smtp.mail.yahoo.com
SMTP_PORT=587
SMTP_USER=you@yahoo.com
SMTP_PASS=app_password
SMTP_FROM=you@yahoo.com
```

Then just run:

```bash
python3 -m uvicorn ui:app --reload --port 8080
```

## Google Sheets logging (optional)

Log each quote to a Google Sheet using a Service Account.

1) Create a Service Account and download the JSON key.  
2) Share your Google Sheet with the service account email (Editor).  
3) Set env vars:

```
SHEET_ID=your_sheet_id
SHEET_TAB=Sheet1
SHEETS_CREDENTIALS_PATH=/path/to/service_account.json
```

Restart the UI server and each confirmed quote will append a row.

## How to add materials or job types

- Materials: insert new rows into `materials` in `Context/materials.sqlite`.
- Job types: update `BOM_PER_UNIT` in `app.py`, then rebuild the Docker image.

## MongoDB migration (materials)

To move existing materials into MongoDB:

1) Set `MONGODB_URI`, `MONGODB_DB`, `MONGODB_MATERIALS_COLLECTION` in `.env`.
2) Run:

```bash
python3 migrate_sqlite_to_mongo.py
```

When `MONGODB_URI` is set, the app reads materials from MongoDB instead of SQLite.

## Notes / Limitations

- Template rendering is minimal and supports the current `quote_template.md` placeholders.
- Currency conversion is not implemented; currencies should match.
# BakeryNation
