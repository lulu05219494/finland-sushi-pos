# Lumo receipt-extraction backend

FastAPI service that sends a photographed Finnish receipt to Gemini
(`gemini-2.5-flash` by default) and returns structured JSON — store name, date,
total, and line items. Fields it can't read confidently come back as `null`,
never a guess.

## Setup

```bash
cd lumo-backend
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
copy .env.example .env        # Windows: copy, macOS/Linux: cp
```

Get a free API key at https://aistudio.google.com/apikey and put it in `.env`
as `GOOGLE_API_KEY`. `gemini-2.5-flash` has a Google AI Studio free tier and
handles Finnish text and umlauts (ä/ö/å) well — no cost to run this.

## Run

```bash
uvicorn main:app --reload --port 8000
```

Check it's up: `curl http://localhost:8000/health`

## API

`POST /api/receipts/extract` — multipart form with a single field `file`
(JPEG/PNG/WebP/HEIC, ≤10MB).

```bash
curl -X POST http://localhost:8000/api/receipts/extract \
  -F "file=@/path/to/receipt.jpg"
```

Response:

```json
{
  "store_name": "K-Citymarket Riihimäki",
  "date": "2026-08-15",
  "total_amount": 27.33,
  "items": [{ "name": "MERILOHI FILEOITUNA", "price": 27.33 }],
  "warning": null
}
```

Any field the model isn't confident about is `null` (or `[]` for `items`);
`warning` lists which ones, so the frontend can flag them for manual review
instead of silently trusting a guess.

## Wiring it into Lumo's frontend

See `frontend-integration.js` — it replaces the `parseFilenameHints()` call
inside `handleFiles()` in `sushi-erp.html` with a real call to this API.

**This only works once Lumo runs as a normal web page** (open the HTML file
directly, or serve it — e.g. add `app.mount("/", StaticFiles(directory="...",
html=True))` to this same FastAPI app). A page published as a claude.ai
Artifact runs in a sandbox whose CSP only permits requests to Google Fonts;
`fetch()` to this backend is blocked there regardless of CORS settings.

## Notes

- `FRONTEND_ORIGINS` in `.env` controls CORS — set it to your real origin(s)
  before deploying; `*` is for local development only.
- The free tier has request-rate limits (check current limits on the
  [Gemini API pricing page](https://ai.google.dev/pricing)); this service
  makes one Gemini call per uploaded receipt with no retries or queueing.
