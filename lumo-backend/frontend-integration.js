/*
 * Drop-in replacement for Lumo's filename-heuristic receipt parsing.
 *
 * In the Lumo single-file app (sushi-erp.html), `handleFiles()` currently calls
 * `parseFilenameHints(file.name)` inside a `setTimeout(...)`. Replace that whole
 * setTimeout block with the async call below, which hits this FastAPI backend
 * instead and maps its response onto the same `invoice` fields.
 *
 * IMPORTANT — Claude Artifacts sandbox: a page published as a claude.ai Artifact
 * runs under a CSP that only allows requests to Google Fonts; fetch() to any other
 * host (including localhost:8000) is blocked there. This integration only works
 * once Lumo is self-hosted as a normal web page (open the .html file directly, or
 * serve it from any static host / the same FastAPI app via StaticFiles).
 */

const RECEIPT_API_URL = "http://localhost:8000/api/receipts/extract"; // change for deployment

async function extractReceiptViaBackend(file) {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(RECEIPT_API_URL, { method: "POST", body: formData });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `请求失败 (HTTP ${res.status})`);
  }
  return res.json(); // { store_name, date, total_amount, items, warning }
}

/*
 * Inside handleFiles(), replace:
 *
 *   setTimeout(()=>{
 *     const hints = parseFilenameHints(file.name);
 *     ... 本地文件名解析 ...
 *   }, 900 + Math.random()*500);
 *
 * with:
 */
async function runRealExtraction(invoice, file) {
  try {
    const result = await extractReceiptViaBackend(file);

    const items = Array.isArray(result.items) ? result.items : [];
    const itemSummary = items
      .map((it) => (it.price != null ? `${it.name} (${it.price}€)` : it.name))
      .join("; ");

    const vatRate = 13.5; // Lumo's default food-service rate; adjust per-invoice as needed
    const amountExcl =
      result.total_amount != null ? Math.round((result.total_amount / (1 + vatRate / 100)) * 100) / 100 : 0;

    Object.assign(invoice, {
      status: "pending",
      vendor: result.store_name || "",
      item: itemSummary,
      date: result.date ? new Date(result.date).toISOString() : new Date().toISOString(),
      amountExcl,
      vatRate,
      category: state.invoiceCategories[0],
      note: result.warning
        ? `Gemini 未能确定：${result.warning}，请核对后确认入账`
        : "已由 Gemini 从图片中识别，请核对后确认入账",
    });
  } catch (err) {
    Object.assign(invoice, {
      status: "pending",
      vendor: "",
      item: "",
      note: `识别失败：${err.message}，请手动填写`,
    });
  }

  saveState();
  if (document.getElementById("view-invoices").classList.contains("active")) renderInvoices();
  updateNavBadges();
}

// And call it in place of the setTimeout(...) block:
//   runRealExtraction(invoice, file);
