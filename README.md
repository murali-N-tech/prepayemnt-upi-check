<h1 align="center">Edge AI UPI Behaviour Risk System</h1>

<p align="center">
A pre-payment risk check for UPI: score the payee <i>and</i> the payer before the money moves.
</p>

<p align="center">

![Python](https://img.shields.io/badge/Python-3.10-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-Backend-green)
![React](https://img.shields.io/badge/React-18-61dafb)
![TypeScript](https://img.shields.io/badge/TypeScript-5.4-3178c6)
![License](https://img.shields.io/badge/license-MIT-blue)

</p>

---

## The problem

UPI apps warn you *after* the money has gone. By then the fraud is a
complaint, not a decision. This project moves the decision to the moment
before payment, and it does so from two directions at once:

- **The payer side** — is this payment unusual *for you*, judged against a
  behaviour profile built from your own uploaded statements?
- **The payee side** — is the address you are paying safe, judged from what
  it looks like and what everyone else's money has done there?

The payee side matters because the payer side cannot see the most common
case. A first-time victim paying a scammer ₹800 looks completely normal:
right amount, right time of day, right device. Nothing about the *payer* is
wrong. Everything wrong is in the *payee*.

---

## What it does

### Check a payee (the pre-payment check)

Paste a UPI ID, the contents of a QR code, or a phone number.

**Address analysis** — validates the address, checks the handle against the
real PSP list, and detects impersonation. Look-alike detection folds
visually similar characters on both sides of every comparison, so `sb1support`
matches `sbi` + `support`.

The brand name on its own is deliberately *not* treated as a risk:
`swiggy@ibl` and `irctc@paytm` really are those merchants. What marks a fake
is the brand paired with a lure word (`sbi-refund`, `hdfcbank-kyc`), a
near-miss spelling (`icicl`), or a handle built to be misread (`okax1s`).

**QR payload parsing** — a UPI QR is a deep link, so its contents can be
checked even though a person cannot read them:

```
upi://pay?pa=rakesh9911@ybl&pn=Reliance%20Digital&am=48999
             └── who gets paid        └── what the QR displays
```

The display name and the address do not belong to each other. That mismatch
is the signature of a sticker pasted over a shop's real code, and it is
invisible to the eye. The parser also rejects a QR whose scheme is not
`upi://` and flags a `url` parameter smuggled into a payment request.

**Payee reputation** — aggregates pooled across payers: when the address was
first seen, how many distinct people have paid it, how many came back, how
tightly the amounts cluster, and how many people reported it. This is the
part a single wallet app cannot do. A collection account has a shape — days
old, many unrelated payers, almost nobody pays twice — and that shape only
appears when payers are pooled. Aggregates only; no payer can read another
payer's transactions from it.

**A four-way decision**, not a block button:

| Decision | Means |
|---|---|
| `APPROVE` | Nothing suspicious found |
| `WARN` | Worth a second look |
| `STEP_UP` | Verify the payee before sending |
| `BLOCK` | Do not pay this |

The middle bands are the point. *"This payee is nine days old and 24 people
have paid it once each — are you sure?"* is more useful than a refusal.

### Statement-based behaviour profiling

Upload a UPI or bank statement (PDF or CSV) to build a personal baseline:
typical amount, usual hours, familiar merchants, known UPI IDs, daily
velocity. A pending payment is then scored against *your* history.

The PDF parser tries four extraction strategies and keeps whichever finds
the most transactions, including a dedicated Google Pay block reader and a
fix for statement generators that render every glyph twice.

---

## Running it

Two processes. Both are needed: Express serves the UI and the behaviour
engine, FastAPI owns PDF parsing and the payee intelligence.

```bash
# 1. dependencies
npm install
pip install -r requirements.txt

# 2. configuration
cp .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"   # paste into JWT_SECRET

# 3. the Python service (PDF parsing + payee checks)
python backend/main.py                      # http://127.0.0.1:8000

# 4. the app
npm run dev                                 # http://localhost:3001
```

Open <http://localhost:3001>, create an account, and the **Check a Payee**
page is the landing page.

To seed the reputation store from statements already uploaded, and to add
four clearly named `demo-*` addresses that exhibit the patterns the detector
looks for:

```bash
python scripts/bootstrap_payee_reputation.py --with-demo-payees
```

### Other commands

```bash
npm run typecheck     # tsc --noEmit
npm run build         # typecheck, then build
pytest tests -q       # 66 tests
```

---

## Architecture

```
                React SPA  (src/)
                     │  /api/*
                     ▼
        ┌────────────────────────────┐
        │  Express  server.ts :3001  │  auth · behaviour engine
        │                            │  CSV parsing · serves the SPA
        └──────────┬─────────────────┘
                   │ proxies PDF upload + payee checks
                   ▼
        ┌────────────────────────────┐
        │  FastAPI  backend/ :8000   │  PDF parsing
        │                            │  VPA · QR · payee reputation
        └──────────┬─────────────────┘
                   ▼
            data/behavior_profiles.db
            statement_transactions · behavior_profiles
            payee_reputation · payee_payers · payee_reports
```

The payee intelligence lives only in Python and Express forwards to it, so
there is exactly one implementation of it.

| Path | What is there |
|---|---|
| `src/` | React app |
| `server.ts` | Express: auth, behaviour scoring, CSV parsing, SPA host |
| `backend/app/services/vpa.py` | address validation, impersonation detection |
| `backend/app/services/upi_qr.py` | UPI deep-link / QR parsing |
| `backend/app/services/payee_reputation.py` | pooled payee aggregates |
| `backend/app/services/payee_check.py` | combines them into a decision |
| `backend/app/services/statement_parser.py` | PDF and CSV extraction |
| `scripts/` | data repair and reputation bootstrap |
| `tests/` | 66 tests |
| `dashboard/` | an earlier Streamlit prototype, kept for reference |

---

## What is a model and what is a rule

Being precise about this matters more than a headline accuracy number.

**Rules and graph analysis** — the payee check and the personalized risk
engine are explicit, inspectable rules with named thresholds. Every finding
carries the reason it fired. This is a deliberate choice: a fraud decision a
user cannot be told the reason for is not much use to them.

**Machine learning** — `backend/train_model.py` fits an Isolation Forest and
a Logistic Regression, but **on synthetic data with rule-derived labels**, so
the classifier can only relearn the rule it was trained on. It is a
placeholder, not a result, and no accuracy figure from it should be quoted.
No public labelled UPI fraud dataset exists; training the classifier on a
real labelled set (IEEE-CIS, PaySim) and reporting recall at a fixed
false-positive rate is the next piece of work.

---

## Known limitations

- The classifier is trained on synthetic data (above).
- Express and FastAPI keep separate user stores, so a profile built from a
  CSV upload (Express, JSON) is not visible to the payee check's payer-side
  comparison (FastAPI, SQLite).
- The reputation store is seeded from uploaded statements, so it reflects
  this deployment's users only.
- Phone-number payees resolve to whoever holds the number today; the check
  says so rather than pretending otherwise.
- `dashboard/` and the legacy pypdf extractors are earlier work kept for
  reference; four tests covering the latter are marked `xfail`.

---

# Author

**N. Unni Krishna**

AI / ML Developer

Focused on building intelligent systems for:

• Fraud Detection
• Behavioural Analytics
• Financial Risk Intelligence

---

# Support

If you found this project interesting, consider giving the repository a **star ⭐** to support development.
