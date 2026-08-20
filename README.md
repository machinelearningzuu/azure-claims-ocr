# Claims OCR — Human-in-the-Loop (Learning Project)

A deliberately small app that contains a real system-design pattern:
**queue + worker + human-in-the-loop**, as used in bounded-AI claims
automation.

```
Upload a claim document
  → OCR extracts fields, each with a confidence score      (the AI step)
  → result goes into a PENDING-REVIEW queue, NOT the DB    (AI proposes, doesn't decide)
  → a human reviews every field against the document       (human-in-the-loop gate)
  → low-confidence fields are flagged for attention        (confidence routing)
  → only on human APPROVE is it written to the database    (the commit)
```

The invariant, enforced in code: **AI output is a proposal sitting in a
queue, never a committed fact.** There is no code path from OCR output to
the database that doesn't pass through the approve endpoint — through a
human.

## Build layers

| Layer | What | Status |
|---|---|---|
| 1 | Real Azure OCR + in-process queue + SQLite. Full human-in-the-loop flow. | ✅ this code |
| 2 | Swap SQLite → Azure Database for PostgreSQL (same DB interface) | not yet |
| 3 | Swap in-process queue → Azure Service Bus + separate OCR worker process | not yet |
| 4 | Containerise, deploy to Azure Container Apps, GitHub Actions CI/CD | not yet |

## Code map

```
app/
  main.py          FastAPI routes — the human-in-the-loop gate lives here
  ocr.py           OCR interface:   extract_fields(bytes) -> [{name, value, confidence}]
  review_queue.py  Queue interface: publish(item) / consume()   (in-process for Layer 1)
  db.py            DB interface:    save_approved(...) / list_approved()  (SQLite for Layer 1)
  models.py        Shared shapes: PendingClaim (proposal) vs approved claim (fact)
  config.py        All configuration from .env
  static/index.html  The review page (plain HTML + JS)
scripts/
  make_sample_claim.py  Generates a fake claim PDF for testing
```

Each external dependency (OCR, queue, DB) sits behind its own small
interface file, so Layers 2–3 swap implementations without touching app
logic.

## Prerequisites

- Python 3.11+
- An **Azure Document Intelligence** resource (portal setup steps are in the
  chat / below in short form) — you need its **endpoint** and **key**.

## Setup (VS Code)

Open this folder in VS Code (`File → Open Folder…`), then in the VS Code
terminal:

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # macOS/Linux; VS Code will offer to auto-use it

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure secrets
cp .env.example .env
#    → edit .env and paste your Document Intelligence endpoint + key
#      (portal: your resource → "Keys and Endpoint")

# 4. (Optional but recommended) generate a fake claim PDF to test with
python scripts/make_sample_claim.py

# 5. Run the app
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 in your browser.

## Testing the flow

1. Upload `sample_claim.pdf` (or any scanned claim-like PDF/image).
   The request goes to real Azure Document Intelligence over the internet —
   expect a few seconds.
2. The review pane shows the nine fields with confidence badges. Red rows
   are below the confidence threshold (default 0.80, set in `.env`) — the
   AI itself is unsure. Fields the OCR couldn't find at all appear empty at
   0% for you to fill in.
3. Deliberately corrupt a value, then fix it — what you approve is what's
   stored, not what the OCR said.
4. Click **Approve**: only now does anything reach the database
   (`claims.db`). Or **Reject**: the proposal vanishes, nothing stored.
5. Upload two documents back-to-back to see the queue hold the second one
   while you review the first.

To inspect the DB directly:

```bash
sqlite3 claims.db "select member_name, diagnosis, approved_at from approved_claims;"
```

## Azure setup for Layer 1 (short form)

Portal → **Create a resource** → search **"Document Intelligence"** →
Create. Free **F0** tier is enough. After deployment: resource →
**Keys and Endpoint** → copy KEY 1 + Endpoint into `.env`.

Free-tier limits to know: 500 pages/month, 20 calls/minute, and only the
**first 2 pages** of each document are processed — all fine for this project.

## Known Layer 1 limitations (intentional — they motivate the next layers)

- The pending queue is in-process: restart the server and unreviewed
  proposals are gone. Layer 3's Service Bus fixes durability.
- OCR runs inside the upload request, so the browser waits on Azure.
  Layer 3 moves it to a separate worker pulling from the queue.
- SQLite is a local file. Layer 2 moves to Azure PostgreSQL.
# azure-claims-ocr
