# Claims OCR: Human-in-the-Loop (Learning Project)

A deliberately small app that contains a real system-design pattern:
**queue + worker + human-in-the-loop**, as used in bounded-AI claims
automation for superannuation.

The invariant, enforced in code: **AI output is a proposal, never a
committed fact.** Every claim lives in the database with a status
(pending_review, in_review, approved, rejected), and the only code path
that can set status=approved is the approve endpoint, which means a human.

## The flow

```
Upload a claim document
  → OCR extracts fields, each with a confidence score     (the AI step)
  → result is persisted with status PENDING_REVIEW        (AI proposes, doesn't decide)
  → a human reviews every field against the document      (human-in-the-loop gate)
  → low-confidence fields are flagged for attention       (confidence routing)
  → empty mandatory fields block approval until the
    human fills them or explicitly confirms the gap       (the approval gate)
  → only human APPROVE moves it to status APPROVED        (the commit)
```

The database is the system of record for the whole lifecycle, so a server
restart loses nothing: pending and mid-review claims are still there
afterwards. The queue is derived from claim status, never a store of its
own (the transactional-outbox idea): in Layer 3, Azure Service Bus will
dispatch work to a separate OCR worker while the database stays the truth.

## Project structure

```
app/
  main.py              FastAPI routes. Both gates live here and nowhere else.
  models.py            Data shapes + loads the template registry from YAML
  config.py            Environment configuration (.env)
  services/
    ocr_service.py     AI/extraction service (Azure Document Intelligence)
    queue_service.py   Review queue, a facade over claim status in the DB
    db_service.py      System of record: claim lifecycle + approved facts
  static/index.html    The review page (plain HTML + JS, renders from /template)
config/
  templates.yaml       Field schema per document template: names, labels,
                       mandatory rules, OCR label synonyms. Pure configuration.
scripts/
  make_dataset.py      Generates the test dataset from the real form templates
docs/templates/        Real claim-form templates (extracted from the client's
                       Process Definition Document, which itself stays out of git)
dataset/               Generated test documents (PDF) + ground truth (JSON)
tests/                 Unit tests for the gate rule and the OCR field matcher
```

Design rules:

- Every external dependency (OCR, queue, DB) lives behind its own service
  module with a small stable interface. Swapping an implementation touches
  one file.
- The field schema is configuration, not code. `config/templates.yaml`
  declares what each document template extracts and what is mandatory; the
  app validates it at startup through typed models. Supporting a new form
  is a YAML edit, not a code change.
- Secrets live in `.env` (gitignored). Nothing sensitive is in code or git.

## Build layers

| Layer | What | Status |
|---|---|---|
| 1 | Real Azure OCR + in-process queue + SQLite. Full human-in-the-loop flow. | done |
| 2 | Swap SQLite for Azure Database for PostgreSQL (same db_service interface) | next |
| 3 | Swap the in-process queue for Azure Service Bus + a separate OCR worker | later |
| 4 | Containerise, deploy to Azure Container Apps, add CI/CD | later |

## Quick start

Prerequisites: Python 3.11+, and an Azure Document Intelligence resource
(portal: Create a resource → "Document Intelligence" → Free F0 tier).

```bash
# 1. Virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Dependencies (app + dev tools)
pip install -r requirements.txt -r requirements-dev.txt

# 3. Secrets: copy the example and paste your endpoint + key
#    (portal: your Document Intelligence resource → Keys and Endpoint)
cp .env.example .env

# 4. Generate the test dataset (18 filled claim forms + ground truth)
python scripts/make_dataset.py

# 5. Run
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000.

## Trying the flow end to end

1. Upload a few dataset PDFs (the file picker accepts multiple). Each goes
   to real Azure Document Intelligence, so expect a few seconds per file.
2. The review queue lists every unsettled document by name. Click any of
   them, in any order; approved and rejected documents leave the list.
   Amber rows are low-confidence (threshold 0.80, configurable in `.env`).
   Red rows are mandatory fields the OCR found empty.
3. Compare the screen against the ground truth JSON next to the PDF: what
   did OCR get right, get wrong, and miss entirely?
4. Corrupt a value, then fix it. What you approve is what gets stored, not
   what the OCR said.
5. Upload a `*_gaps.pdf` and click Approve without touching anything. The
   gate refuses. Fill the missing field, or tick "confirm missing" to make
   the skip an explicit, recorded decision.
6. Approve: only now does anything reach `claims.db`. Reject: the proposal
   vanishes and nothing is stored.

Inspect the database directly:

```bash
sqlite3 claims.db "select approved_at, json_extract(fields_json,'$.surname') as surname, confirmed_missing_json from approved_claims;"
```

## The test dataset

`scripts/make_dataset.py` writes 6 fictional personas x 3 variants = 18
two-page PDFs onto the real MetLife form pages, each with a ground-truth
JSON recording every value and every deliberately blank field:

- `*_full.pdf`: every field filled
- `*_mandatory_only.pdf`: mandatory fields only
- `*_gaps.pdf`: mandatory-only minus 1-2 mandatory fields, to trip the gate

Ground truth exists so OCR accuracy can be scored, not just eyeballed.
All personal data in the dataset is fictional.

## Branch workflow

- `main` stays deployable at all times.
- Every change is a feature branch and a pull request: for example
  `layer-2-postgres`, `layer-3-servicebus-worker`, `layer-4-deploy`.
- Before pushing, run what a future CI pipeline will run:

```bash
ruff check . && pytest -q
```

CI/CD is intentionally not set up yet. It arrives with Layer 4; the branch
discipline above is shaped so a pipeline can slot in without restructuring.

## Azure notes (Layer 1)

Free F0 tier limits: 500 pages/month, 20 calls/minute, and only the first
2 pages of each document are processed. The dataset PDFs are exactly 2
pages, so nothing is lost.

## Known Layer 1 limitations (intentional, they motivate the next layers)

- OCR runs inside the upload request, so the browser waits on Azure.
  Layer 3 moves it to a separate worker, with Service Bus dispatching the
  work while the database remains the system of record.
- SQLite is a local file. Layer 2 moves to Azure PostgreSQL.
- Single reviewer assumed: no locking against two people pulling the same
  claim. Fine for a learning project with one human in the loop.
