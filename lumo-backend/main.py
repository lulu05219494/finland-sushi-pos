"""
Lumo receipt-extraction backend.

Receives a photographed receipt (mainly Finnish grocery/food-service receipts:
K-Citymarket, K-Supermarket, K-Market, S-market, Prisma, Lidl, ...), sends it to
Gemini as a multimodal request, and returns structured JSON:

    {
      "store_name": str | null,
      "date": "YYYY-MM-DD" | null,
      "total_amount": float | null,
      "items": [{"name": str, "price": float | null}, ...],
      "warning": str | null
    }

Fields the model isn't confident about come back as null / empty — the prompt
explicitly forbids guessing, per the product requirement that a failed read
must surface as "unrecognized", never as fabricated data.
"""

import json
import os
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from google.genai import types
from pydantic import BaseModel

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_MODEL_NAME = os.getenv("GOOGLE_MODEL_NAME", "gemini-2.5-flash")
FRONTEND_ORIGINS = [o.strip() for o in os.getenv("FRONTEND_ORIGINS", "*").split(",") if o.strip()]
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}

app = FastAPI(title="Lumo Receipt Extraction API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

_client: Optional[genai.Client] = None


def get_client() -> genai.Client:
    global _client
    if not GOOGLE_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="GOOGLE_API_KEY is not configured on the server. Set it in .env (see .env.example).",
        )
    if _client is None:
        _client = genai.Client(api_key=GOOGLE_API_KEY)
    return _client


class ReceiptItem(BaseModel):
    name: str
    price: Optional[float] = None


class ReceiptExtraction(BaseModel):
    store_name: Optional[str] = None
    date: Optional[str] = None
    total_amount: Optional[float] = None
    items: List[ReceiptItem] = []


class ExtractionResponse(BaseModel):
    store_name: Optional[str] = None
    date: Optional[str] = None
    total_amount: Optional[float] = None
    items: List[ReceiptItem] = []
    warning: Optional[str] = None


PROMPT = """You are reading a photographed retail or food-service receipt (kassakuitti) \
from Finland. It may come from chains such as K-Citymarket, K-Supermarket, K-Market, \
K-Extra, S-market, Prisma, Lidl, Sale, Alepa, Kespro, Meira Nova, or a similar Finnish \
supplier. Receipts are printed in Finnish and may contain umlauts (ä, ö, å) and heavily \
abbreviated product names (e.g. "MERILOHI FILEOITUNA").

Extract exactly these fields from the image:

- store_name: the store or chain name printed at the top of the receipt.
- date: the purchase date, converted to ISO format YYYY-MM-DD. Finnish receipts \
usually print it as DD.MM.YYYY.
- total_amount: the final amount actually paid (look for "YHTEENSÄ" / "VEROLLINEN" / \
the card payment "Debit/Charge" line), as a plain number using "." as the decimal \
separator. Do not include a currency symbol.
- items: every distinct product or line item on the receipt, in the order printed. \
For each: "name" is the printed product text verbatim (keep the original Finnish — \
do not translate it), and "price" is that line's charged total as a plain number.

Rules:
- If a field cannot be read with confidence, return null for it (or an empty list for \
items) — never guess, invent, or approximate a value that is not actually legible in \
the image.
- If the image is not a receipt at all, or is unreadable, return null for every field \
and an empty items list.
- Respond with JSON only, matching the provided schema."""


async def _read_upload(file: UploadFile) -> bytes:
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported content type '{file.content_type}'. Allowed: {sorted(ALLOWED_CONTENT_TYPES)}",
        )
    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File exceeds {MAX_UPLOAD_BYTES // (1024*1024)}MB limit.")
    return data


def _parse_model_output(response) -> ReceiptExtraction:
    if getattr(response, "parsed", None) is not None:
        return response.parsed  # already a validated ReceiptExtraction instance

    # Fallback: some responses omit .parsed even with response_schema set — recover
    # the JSON from .text so a formatting hiccup doesn't turn into a hard failure.
    text = (getattr(response, "text", None) or "").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    if not text:
        raise HTTPException(status_code=502, detail="Gemini returned an empty response.")
    try:
        return ReceiptExtraction.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Could not parse Gemini's response as JSON: {exc}") from exc


@app.get("/health")
def health():
    return {"status": "ok", "model": GOOGLE_MODEL_NAME, "configured": bool(GOOGLE_API_KEY)}


@app.post("/api/receipts/extract", response_model=ExtractionResponse)
async def extract_receipt(file: UploadFile = File(...)):
    image_bytes = await _read_upload(file)
    client = get_client()

    try:
        response = await client.aio.models.generate_content(
            model=GOOGLE_MODEL_NAME,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=file.content_type),
                PROMPT,
            ],
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
                response_schema=ReceiptExtraction,
            ),
        )
    except Exception as exc:  # network errors, auth errors, quota errors, etc.
        raise HTTPException(status_code=502, detail=f"Gemini request failed: {exc}") from exc

    result = _parse_model_output(response)

    missing = []
    if not result.store_name:
        missing.append("store_name")
    if not result.date:
        missing.append("date")
    if result.total_amount is None:
        missing.append("total_amount")
    if not result.items:
        missing.append("items")
    warning = f"Could not confidently read: {', '.join(missing)}" if missing else None

    return ExtractionResponse(**result.model_dump(), warning=warning)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=True)
