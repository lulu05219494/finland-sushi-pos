# Lumo — Finnish Sushi POS

A restaurant back-office prototype for a Finnish sushi shop, combining
ERPNext-style POS/inventory (BOM-driven stock deduction, Viva.com card
terminal flow) with TaxHacker-style receipt/invoice AI extraction.

## Structure

- **`lumo-frontend/index.html`** — single-file frontend (POS, inventory, BOM,
  invoices, VAT reporting). Open directly in a browser; state persists in
  `localStorage`.
- **`lumo-backend/`** — FastAPI service that calls Gemini (`gemini-2.5-flash`)
  to extract structured data from photographed receipts. See
  `lumo-backend/README.md` for setup.

## Quick start

```bash
cd lumo-backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # then add your GOOGLE_API_KEY
uvicorn main:app --reload --port 8000
```

Then open `lumo-frontend/index.html` in a browser, go to the invoices page,
point "识别后端" at `http://localhost:8000`, and test the connection.
