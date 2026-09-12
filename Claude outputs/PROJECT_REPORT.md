# Graph-Based Real-Time UPI Fraud Detection and Scam Link/QR Identifier System

**Full project audit and report**
Murali — B.Tech final year · 12 September 2026

---

## 1. What this report is

You asked me to analyse the whole project, remove every major and minor bug including
miscalculations, fix them, and write the report. This is that report.

It is written to be read by an examiner. That means it states what the system does, what
the numbers actually are, and what it does **not** do. Several sections below correct claims
the project was previously making about itself. That is deliberate: a fraud system that
overstates its own accuracy is the one failure mode a reviewer will always find, and it is
better found here.

**The two most important findings**, both about the training data:

1. **It was leaking the label.** `payee_distinct_payers` was a whole number for every
   legitimate row and a fraction for 99.6% of fraud rows. A single decision-tree split on
   "is this a whole number?" separated the classes perfectly.
2. **It did not cover the amounts UPI actually allows.** UPI caps a single transaction at
   ₹1 lakh. The simulator's amounts topped out around ₹61,000 — 3 rows in 120,000 above
   ₹50,000 and *none at all* above ₹70,000 — so the model never saw the top 30% of the
   legal range and its prediction came out **flat at 0.4034 from ₹5,000 to ₹1,00,000**. It
   could not tell an ordinary payment from a maxed-out drain, which is the signature of an
   account takeover. The bare `amount > 70000` rule in `/predict` was quietly doing that
   job instead.

Every accuracy figure the project reported was measuring the first of those. The honest
figures, after both fixes, are in §4.

---

## 2. What the system is

A pre-payment check. The user is about to pay — they have scanned a QR, pasted a UPI ID, or
typed a phone number — and the system answers **before** the money moves, in four levels:
APPROVE / WARN / STEP_UP / BLOCK.

It combines six independent streams of evidence.

| # | Stream | What it reads | Module |
|---|--------|---------------|--------|
| 1 | Address | Is the VPA valid? Does it impersonate a brand via look-alike characters? | `vpa.py` |
| 2 | QR payload | Was the request tampered with — a name that doesn't match the address, a locked amount, a smuggled link? | `upi_qr.py` |
| 3 | Payee history | What has *everyone else's* money done at this address? | `payee_reputation.py`, `fraud_graph.py` |
| 4 | Amount context | Is this large, to a stranger? | `payee_check.py` |
| 5 | Stated purpose | Does what the payer thinks they're doing contradict who gets the money? | `intent.py` |
| 6 | Message pressure | What does the message that caused this payment say? | `coercion.py` |
| + | Scam links | Any URL in the message or QR — look-alike domain, brand impersonation | `scam_link.py` |

Plus a trained classifier over the payer's own behaviour and the payee's graph position
(`ml/features.py`, `train_model.py`), and the payer's statement-derived baseline
(`personalized_risk_service.py`).

### 2.1 Why the combination rule is the interesting part

Adding six scores saturates on any two moderate signals; taking the maximum throws away
corroboration. So:

- One strong signal leads; the others add a damped 40%.
- **Independent families agreeing** earns a bonus (2 families → +6, up to 6 families → +32).
  Each family votes once, so a message with four scam patterns still counts once — what is
  rewarded is independent streams agreeing, not volume.
- A short list of findings hard-block regardless of arithmetic (`payee_blocked`,
  `vpa_malformed`, `not_a_payment_link`, `no_payee`).

This is policy, not a model output, and the thresholds are named constants
(`BLOCK_AT = 70`, `STEP_UP_AT = 45`, `WARN_AT = 22`) precisely so an examiner can argue
with them.

---

## 3. Architecture

```
React 18 + TS (Vite)          ──►  Express (server.ts, :3001)  ──►  FastAPI (:8000)
  light/dark, landing + app        thin auth + proxy only            all the logic
  Capacitor Android wrapper                                          SQLite, sklearn,
  Vercel for the web build                                           SHAP, networkx
```

One rule holds the design together: **Express never re-implements logic.** It authenticates
and forwards. Earlier, Express parsed CSVs itself while forwarding only PDFs, and the two
backends produced different profiles for the same user. Now there is exactly one
implementation of everything.

Single SQLite store (`data/behavior_profiles.db`): users, statement lines, behaviour
profiles, scored transactions, payee reputation, and the payer→payee edge list.

---

## 4. Model performance — the honest numbers

Retrained after the leakage fix, with the operating threshold chosen on a **validation**
split and measured on a **test** split it never saw.

**Data**: 120,000 simulated transactions, 1.18% fraud, every amount inside the ₹1 lakh UPI
per-transaction cap and the whole legal range populated in both classes. 72,000 train /
18,000 validation / 30,000 test (355 fraud rows in test).

| Metric | Logistic baseline | **Selected: HistGradientBoosting** |
|---|---|---|
| ROC-AUC | 0.9511 | **0.9702** |
| PR-AUC | 0.3331 | **0.5284** |
| Recall @ 1% FPR budget | 30.1% | **55.8%** |
| Realised FPR on test | — | **0.93%** |
| Precision at that point | 28.8% | **41.8%** |
| Brier | — | **0.0077** |

Brier alone is meaningless, so the reference is reported beside it: always predicting the
base rate scores **0.01169**, which makes the selected model's **Brier skill score +0.342** —
it removes 34% of the reference error. Say that, not "Brier 0.0077, which is very low".

**Recall by fraud type**, at the same 1% false-positive budget:

| Scenario | n | Recall |
|---|---|---|
| Card testing (tiny probe payments) | 20 | 100.0% |
| Account takeover | 73 | 93.2% |
| Mule collection | 80 | 72.5% |
| **Social engineering** (payer authorised it) | 182 | **28.6%** |

Unsupervised half: IsolationForest fitted on legitimate traffic only, ROC-AUC 0.8368.

### 4.0 Why these numbers are lower than the previous draft

An earlier run of this report quoted PR-AUC 0.6187 and social-engineering recall 58.4%.
Those came from a dataset whose amounts could not exceed ₹61,000. Once legitimate large
payments exist — rent, fees, deposits, hospital bills, all the way to the ₹1 lakh cap —
they genuinely overlap the fraud scenarios, and the problem gets harder. Social-engineering
recall fell from 58.4% to 28.6%; account-takeover recall rose from 73.2% to 93.2%, because a
drain that maxes out the limit is now expressible and the model learns it.

That trade is the right one. The old 58.4% was partly measuring a population in which nobody
paid rent.

### 4.1a The model can now see the amount range

Measured on an unseen seed, at the chosen threshold:

| Amount band | Fraud n | Recall | Legit n | False-positive rate |
|---|---|---|---|---|
| ₹0 – ₹10,000 | 528 | 48.3% | 56,992 | 0.83% |
| ₹10,000 – ₹25,000 | 22 | 63.6% | 1,354 | 1.62% |
| ₹25,000 – ₹50,000 | 37 | 51.4% | 593 | 6.58% |
| ₹50,000 – ₹70,000 | 15 | 46.7% | 189 | 9.52% |
| **₹70,000 – ₹1,00,000** | 54 | **83.3%** | 216 | 7.41% |

Account-takeover drains above ₹70,000 specifically: **97.6% recall** (n=42).

Two things to say about this honestly. The model now separates a maxed-out transfer from an
ordinary one — that is the point of the fix. But the false-positive rate is *not* uniform: a
person making a genuine large payment has roughly a **7% chance of being warned**, against
0.83% for everyday amounts. The 1% budget is an average over the whole distribution, and
large payments carry more of it. That is defensible — a ₹1 lakh transfer is worth a
confirmation prompt — but it should be stated, not hidden inside the average.

### 4.1 The ablation, stated correctly

The project's original claim was: *a model that sees only the payer's behaviour cannot catch
social engineering, because the payer is behaving normally by definition.* The numbers do
**not** support that claim, and the training script used to print the claim unconditionally
whatever the numbers said. It now reads them.

Social-engineering recall:

| Feature set | Recall |
|---|---|
| Payer behaviour only | 3.9% |
| Payee signals only | 8.8% |
| **Both** | **28.6%** |

On the corrected dataset both halves are nearly blind alone, and together they reach 28.6% —
a **combined lift of +19.8 points over the better single half**, and strongly superadditive
(3.9 + 8.8 = 12.7 against 28.6 measured). That is the defensible claim: neither view of a
payment is sufficient, and the two together are worth more than their sum.

Note that on this dataset the payer-only arm at 3.9% *does* now support the project's
original intuition, where the previous draft's 36.5% contradicted it. The difference is
entirely that legitimate large payments now exist to compete with the fraudulent ones. The
training script prints the comparison rather than asserting a conclusion, so whichever way a
future run falls, it reports what it measured.

Say why streams 5 and 6 (stated purpose, message pressure) exist: the remaining 71.4% is
missed structurally, because the evidence is not in the transaction at all.

### 4.2 The message-pressure model

Separately fitted logistic model over 10 linguistic pattern families, weights stored as
**JSON not a pickle** (so it reproduces across numpy versions — see §6.9).

- Corpus: 1,022 templated messages — 364 scam, 557 hard negatives, 101 easy negatives.
- Held-out (n=307): **recall 74.3%**, false positives on genuine bank messages **0.6%**,
  ROC-AUC 0.968, PR-AUC 0.922.
- Threshold 0.16, chosen as the lowest threshold holding hard-negative false positives
  under 5% **on train**.

The first fit reported 100% recall and PR-AUC 0.995. That was a red flag, not a result: no
hard negative used the strong patterns. Adding legitimate messages that genuinely offer
cashback, charge a processing fee, and request payment dropped recall to 74.3% and cut false
positives from 2.3% to 0.6%. The second number is the real one.

`pay_request` and `credential_request` were moved to the **weak** pattern set with a policy
ceiling of 15, because a genuine overdue-EMI notice scored 50–51 on urgency + fear alone.

### 4.3 The caveat that belongs on every slide

**The transaction data is simulated.** No public labelled UPI fraud dataset exists. These
figures describe the *method*, not field performance. `backend/ml/dataset.py` documents the
generative process; `FEATURES` is the contract, so real labelled data drops in unchanged.

---

## 5. Bugs found and fixed

202 tests pass, including 44 new regression tests written specifically to pin these down.
Everything below was verified by execution before and after the fix, not by inspection.

### 5.0 The UPI per-transaction cap was enforced nowhere

UPI caps a single transaction at **₹1,00,000** for P2P and standard merchant payments, and
**₹5,00,000** for verified merchants in specific categories (insurance, capital markets,
travel, education, healthcare, collections, credit-card bills, tax, GeM) — NPCI, in force
since 15 September 2025. Four parts of the system each assumed something different, and none
of them enforced anything. Measured before the fix:

| Input | What happened |
|---|---|
| `POST /predict {"amount": -5000}` | **200, risk=0, "APPROVED"** |
| `POST /predict {"amount": 1e12}` | 200, scored as a real payment |
| `POST /predict {"amount": 0}` | 200, scored |
| `upi://pay?...&am=99999999` | one *info* finding: "the amount is fixed at ₹99,999,999.00 by the QR" |
| `check_payee("shop@ybl", amount=9999999)` | **WARN** |

A payment of minus five thousand rupees is not a thing, and one lakh crore cannot move over
UPI. Scoring them produces a fraud verdict about a payment that could never happen — which is
worse than an error, because the user is told "APPROVED".

Fixed as one shared authority, `backend/app/core/upi_limits.py`, mirrored on the client in
`src/lib/upiLimits.ts`, with both caps overridable from the environment
(`UPI_MAX_AMOUNT`, `UPI_MAX_AMOUNT_MERCHANT`) because NPCI revises them:

- **Pydantic validators** on `Transaction` and `PersonalizedRiskCheck` → 422 with a plain
  explanation, instead of a fraud verdict.
- **`upi_qr.py`** raises `amount_over_upi_limit` at **critical** severity. A request no app
  can honour is not a payment request; it is a tampered or fabricated QR, which is the whole
  reason for parsing the payload.
- **`payee_check.py`** adds that code to `HARD_BLOCK`, so it decides the outcome regardless
  of the arithmetic: ₹99,99,999 now BLOCKs instead of WARNing.
- **The higher cap is not a free upgrade.** It requires *both* a merchant category code and a
  signature, because an `mc` alone is trivially forged. A pasted UPI ID or a phone number gets
  the standard cap — deliberately conservative, since the cost of guessing wrong is accepting
  an amount UPI would reject.
- **The three amount inputs** now carry `max`, `min`, `step` and an inline message, so ₹1
  crore can no longer be typed, sent, and rejected a round trip later.
- **Zero means "not typed yet"**, not a violation. A first version of this fix blocked a ₹0
  amount under the code `amount_over_upi_limit`, which was simply untrue — the pre-payment
  screen sends 0 before the payer fills the field in.

**And the deeper bug it exposed** · `backend/ml/dataset.py`, `backend/main.py`

The `amount > 70000` hard rule in `/predict` was a bare number doing more work than it looked
like. The simulator's amounts topped out at ₹61,000 — 3 rows in 120,000 above ₹50,000, none
above ₹70,000 — so the model's prediction was **flat at 0.4034 from ₹5,000 to ₹1,00,000** and
that rule was the only thing separating a maxed-out drain from a ₹5,000 payment.

Fixing it took three passes, and the two failed ones are worth recording:

1. **First attempt**: drew legitimate large payments log-uniform across ₹20,000–₹1 lakh for
   everybody. That made a person whose usual payment is ₹270 send ₹80,000 routinely — a 296×
   multiple as ordinary behaviour — and since those rows outnumber the fraud rows 16:1, they
   carpeted the high-ratio region and destroyed `amount_over_user_avg` for everyone.
   Social-engineering recall collapsed to 19.8%.
2. **Second attempt**: scaled the band to each payer's means. Correct in principle, but then
   only 14 legitimate rows sat above ₹70,000 against 120 fraudulent ones, giving
   **P(fraud | amount > ₹70k) = 0.90** against a 1.2% base rate. That is not a property of
   fraud — it is a property of a simulated population with nobody in it who pays rent.
3. **What worked**: widened the user population (`sigma` 0.8 → 1.1, so 3.5% of users have a
   typical payment over ₹2,000 rather than 0.6%) and added the segment that actually exists —
   12% of users who use UPI for rent, fees and hospital bills. Now
   **P(fraud | > ₹70k) = 0.206, a 17.4× lift**: a strong signal the model can learn, not a
   giveaway. Amount alone reaches ROC-AUC 0.687, comfortably under the 0.95 leak guard.

The hard rule stays as a floor — the cost of missing a maxed-out transfer is the whole daily
limit — but it is now written as `amount >= 0.7 * standard_cap()` and the response says
`decided_by: "rule:near_upi_ceiling"` with the cap it was measured against, so it is not
another unexplained constant.

### 5.0b `backend/api.py` — dead code, and the reason the leaked credential exists

Found while checking every module still imports. `backend/api.py` is a **second FastAPI app**
from an earlier architecture, and it cannot be imported at all:

```
$ python -c "import backend.api"
ModuleNotFoundError: No module named 'psycopg2'
```

Beyond psycopg2, it imports five service modules that **do not exist in the repository** —
`velocity_service`, `drift_service`, `graph_fraud_service`, `alert_service`, `shap_service`.
So it has been unrunnable for some time and nothing references it.

It matters for three reasons:

1. **Its scoring is `risk_score = tx.amount * 0.1`, uncapped** — the same class of bug as
   §5.0. At ₹1 lakh that is 10,000 on a scale whose alert threshold is 800, so everything
   above ₹8,000 is a maximum-severity alert. It bears no relation to the trained model.
2. **It has no authentication on any route**, and it writes to Postgres.
3. **It is the sole consumer of `backend/app/core/database.py`**, which is the sole consumer
   of the Postgres credential in your git history — the one in §8 that needs rotating. It is
   also the only reason `psycopg2-binary` is in `requirements.txt` (the comment there already
   says "backend/api.py only").

I have not deleted it, because deleting files is your call. But removing it removes the reason
the credential exists in the project at all:

```bash
git rm backend/api.py backend/app/core/database.py
# then drop the psycopg2-binary line from requirements.txt
```

Everything the live system does is in `backend/main.py`, on SQLite.

### 5.1 Critical — the numbers were wrong

**1. Label leakage in the training data** · `backend/ml/dataset.py`
The legitimate generator wrote `int(np.clip(...))` for `payee_distinct_payers`; all four
fraud generators wrote `float(np.clip(rng.gamma(...)))`. Measured: 99.6% of fraud rows
carried a fractional part, 0% of legitimate rows did, and `P(fraud | fractional) = 1.00`
against a 1.2% base rate. Every reported metric was measuring this.
Fixed with a shared `_count()` helper used by both paths, plus a test that asserts no single
feature reaches ROC-AUC 0.95 alone.

**2. Operating threshold chosen on the test set** · `backend/train_model.py`
`recall_at_fpr` searched the *test* ROC curve for the threshold maximising recall inside the
budget, then reported recall and precision at that threshold *on the same rows* — reporting
the best of ~30,000 thresholds as an unbiased estimate. Now a three-way split: threshold
chosen on validation, measured on test, with the **realised** FPR (0.83%) reported so the
budget is a claim that was actually checked.

**3. A transaction ID read as an amount** · `statement_parser.py`
The amount scorer penalised reference-like numbers but returned the best candidate however
negative its score. `"PhonePe Transaction ID: PP123456789"` scored −18 and came back as
₹123,456,789 — which then became the user's `max_amount` and the denominator of every amount
ratio. Added a score floor; genuine amounts with no currency marker still score ≥ 2.

**4. Four of nine PDF extractors returned nothing** · `statement_parser.py`
The wallet keyword lists contain `"to"`, `"from"`, `"utr"`, `"transaction id"`, and a keyword
match was treated as a record *boundary*. Nearly every line of a PhonePe statement was a
boundary, so one transaction became five blocks, none holding both a date and an amount.
PhonePe, Google Pay, Paytm and BHIM all returned `[]`. The four "environment" test failures
were recording this bug, not an environment problem. Rewrote the splitter so a **date** is
the record boundary and keywords only decide relevance.

**5. Re-uploading a statement duplicated every row** · `profile_store.py`
SQLite treats every NULL as distinct in a UNIQUE index, so the index on
`(user_id, timestamp, amount, merchant, reference_number)` suppressed nothing for exactly the
rows that need it — PDF statement lines with no reference number. Measured: three inserts of
the same row produced three rows. Rebuilt as `ux_stmt_tx_v2` over `COALESCE(...)` expressions;
now 1 → 0 → 0.

**6. Drift detection was a coin flip** · `drift_monitor.py`
It took the mean of the *binary* risk flag over ten rows a side and called a gap above 0.3
drift. Ten Bernoulli samples have a standard error near 0.16, so 0.3 is about two standard
errors — it fired on chance alone, and it declared "Model Stable" with identical confidence
when the data supported neither conclusion. Rewritten to use the continuous score, split the
full history in half, and compare the gap against its own Welch standard error, with a
minimum of 15 rows per window and an explicit inconclusive state.

**7. The heatmap's y-axis was `Math.random()`** · `FraudHeatmap.tsx`
`riskScore: Math.floor(Math.random() * 20) + (risk[idx] === 1 ? 75 : 15)`. The "Fraud
Activity Heatmap" plotted noise, and every reload moved the points. The real `risk_score` was
in the database the whole time; `/heatmap` now returns it.

**8. The rebuild script erased its own repair** · `scripts/rebuild_profiles.py`
`stage_compact` rebuilt the table without the `time_known` column, `_ensure_schema` re-added
it on the next open with `DEFAULT 1`, and every row `fixtimes` had marked "no time recorded"
became a real midnight or noon payment again. `stage_reparse` dropped the flag too, and `all`
ran `fixtimes` **before** `reparse`, which then deleted the rows it had just marked. All four
fixed.

### 5.2 Security

**9. Six endpoints were unauthenticated** · `backend/main.py`
`/heatmap`, `/temporal-patterns`, `/explain/{id}`, `/behavior/{id}`, `/predict` had no auth
dependency. Express required a token, but the Python service is reachable directly — it is
deployed on Render. `/heatmap` returned **every user's payment amounts** to anyone who asked.
All now require the token, and `/heatmap` and `/temporal-patterns` are scoped to the caller.

**10. IDOR on `/explain` and `/behavior`**
Both returned any transaction's amount, payee and full feature vector on id alone. Now
ownership-checked, returning 404 rather than 403 so the response doesn't confirm the id
exists. Verified with two real accounts: owner 200, stranger 404.

**11. `/predict` trusted a client-supplied `sender`**
Anyone could write scored rows under another user's id — the rows `/heatmap`,
`/transactions` and the behaviour profile all read back. The payer is now whoever holds the
token, full stop. Verified: a request sending `sender: "SPOOFED-NOT-ALICE"` stored Alice's
real id.

**12. Guessable, collidable IDs**
`tx_{uuid4().hex[:6]}` is 24 bits: by the birthday bound a 1% collision chance by ~580
payments and 50% by ~4,800 — and `transaction_id` is the PRIMARY KEY written with
`INSERT OR REPLACE`, so a collision silently overwrote someone's payment record. Same shape
in `usr_{hex[:8]}`. Both now use the full UUID.

### 5.3 Wrong numbers shown to the user

**13. Night-transaction ratio, halved** · `UserProfile.tsx` + `statement_parser.py`
`night_transactions` counts only rows with a real clock time; the UI divided by
`transaction_count` (all rows). On a statement where half the rows print no time, the ratio
was halved. Added `timed_transaction_count` and used it as the denominator, labelled
"4 of 4 timed".

**14. Unique payees capped at 10** · `UserProfile.tsx`
`merchant_frequency` is deliberately the top 10; the UI read `Object.keys(...).length` as
"unique payees", a number that could never exceed 10. Now uses the real `distinct_payees`.

**15. Amounts sorted as strings** · `UserProfile.tsx`
`localeCompare` on every column, so ₹900 sorted after ₹1,000 and ₹95 after ₹9,500. Amount
now sorts numerically and timestamp by date.

**16. "Payments" counted links, not payments** · `NetworkGraph.tsx`
`edges.length` is distinct payer→payee *pairs*: a payer who paid one shop forty times is one
edge. Now sums the per-edge `payments` count and shows the pair count as its own figure.

**17. "Model Stable" for a check that never ran** · `SystemMonitor.tsx`
`driftData.drift_status || "Model Stable"` printed a green "Model Stable" when the backend
had answered "not enough data" with no `drift_status` key at all. Now shows the real state,
the margin behind it, and only goes green when the check actually concluded.

**18. "The live payment processing channels are fully secure"** · `FraudAlerts.tsx`
A claim this screen cannot make — recall is 67.6%, so "nothing flagged" and "nothing
happened" look identical, and with zero transactions it said the same thing. Now reports what
was checked: "None of your N most recent payments were flagged. This is what the model found,
not a guarantee."

**19. "No Profile Found" when the backend was down** · `UserProfile.tsx`
Both fetches used `.catch(() => null)`, so a backend outage produced the same screen as a
user who had never uploaded a statement — a false statement about their own data that sent
people to re-upload what they'd already uploaded. Now distinguishes 404 from a fault.

**20. Risk Score 13 next to BLOCKED** · `FraudDetection.tsx`
Both numbers were right: `risk_score` is the calibrated probability × 100, and the threshold
is 0.13 — the point that holds false positives to 1 in 100. Showing the score with no
threshold beside it made them look like a contradiction. Now shows the probability, the
threshold, and what the threshold buys.

**21. Device score inverted** · `FraudDetection.tsx` + `behavioral_biometrics.py`
The slider was labelled **"Device Trust Score"**; the backend treats it as *risk* and adds it
to the behavioural risk. Anyone setting it to 1.00 to mean "this is my own phone" raised the
risk by 0.4 instead of lowering it. The label is fixed and the direction is now documented at
the top of the module.

### 5.4 Backend correctness

**22. The whole coercion UI was invisible** · `server.ts`
`PayeeCheck.tsx` fetches `/api/payee/intents`; that route was never registered in Express.
The entire "why are you paying?" selector — and every coercion finding depending on it —
404'd, while the backend implemented it correctly.

**23. Express dropped the query string** · `server.ts`
`forwardJson` forwarded `target.pathname` only. `/statement-transactions` builds a query
(page, limit) and every request arrived upstream without it, so the API silently returned
page 1 whatever the user clicked. Also: an `https://` upstream got a cleartext request to
port 80, so `PYTHON_BACKEND_URL` could only ever be a local address.

**24. `txn_type` and `time_known` missing on four of five parser return paths**
`profile_store` defaults the absent keys to `DEBIT` and `time_known=1`, so credits joined the
spending average and date-only rows became genuine midnight payments — `most_active_hour` 0
and every row counted as a night transaction. Only one of five return sites had been patched.

**25. Hour-of-day chart mixed IST and UTC** · `temporal_gnn.py`
`utc=True` *converts* an offset-bearing value, so `02:30+05:30` was binned at hour 21 while
the naive row beside it stayed at hour 2. Now strips the offset before parsing, keeping the
clock the payer actually saw.

**26. A name that discards itself** · `upi_verify.py`
A conditional expression binds looser than `or`, so the trailing `if ... else None` guarded
the *whole* or-chain. A provider answering `{"valid": true, "customer_name": "..."}` failed
the condition and the account holder's name was discarded — leaving nothing to show the user
against the name on the QR.

**27. `localStorage` crashed the app in a private window** · `apiConfig.ts`
`localStorage` *throws*, not returns null, when site data is blocked. Every read was bare, so
in those browsers the first call threw during module evaluation and the page rendered blank —
instead of falling back to the relative path that works fine.

### 5.5 Fixed earlier in the audit (verified, summarised)

- `payee_is_new` followed the payee's whole network instead of *this* payer's history — the
  substitution cost most of the model's recall (`features.py`, `payer_has_paid`).
- The amount ratio used a mean where the model was trained on a median; on a long-tailed spend
  distribution the mean sits ~1.4× higher, making every served ratio too small.
- `txns_last_hour` was fed `velocity_score` — a score, not a count. Now a real count over
  ≤3600s, shared by `/predict` and `/explain` through one `_payer_context()` so they cannot
  disagree.
- `/explain` omitted three features entirely and explained a vector the model was never
  given; on roughly 1 transaction in 20 that vector produces the opposite decision.
- SHAP explained against `np.random.rand()` instead of real traffic. Now a 200-row sample of
  the training distribution.
- Clock distance wasn't circular: 02:00 read as 21 hours from a 23:00 baseline instead of 3,
  penalising a night-shift user on every ordinary payment.
- `lifespan_days` used `.days`, which floors: a 2.9-day window became 2 and 10/2 = 5.0 crossed
  the ≥5 threshold that 10/2.917 = 3.43 does not — a fabricated "averaging 5 payments a day".
- The agreement-bonus table stopped at 4 while 6 families exist, so a **fifth** stream agreeing
  dropped the bonus from 22 to 0 and *downgraded* the verdict.
- A QR's embedded URL was scored twice, in two "independent" families, manufacturing agreement
  from one fact.
- QR name-mismatch compared letter overlap: "Ram Store" vs `amitsharma123@ybl` scored 0.857 and
  the mismatch — the whole point of the check — was suppressed. Now token containment.
- `www.icicibank.com` was flagged as brand impersonation; a genuine `irctc.co.in` link plus a
  friend payment was flagged as a brand conflict.
- Degree ≥ 3 "GNN fraud detection" returned popular merchants, because degree measures success.
  Replaced by graph *shape*: one-shot payer ratio, arrival burst, shared payer pools.
- PhonePe times: the font has no ToUnicode mapping for the colon (extracted as `\x00`) and the
  block regex was uppercase-only — 0 of 354 times parsed. Both fixed → 354/354. Then the
  de-dup key collapsed two real ₹20 payments to the same shop, because it had no time or
  reference in it; fixed → correct count.
- `tests/test_model_pipeline.py` **asserted the bug** (`payee_is_new == 1`). Updated, with a
  comment saying the old assertion encoded the defect.

---

## 6. What this system does *not* do

An examiner will ask. Better to have the answers.

1. **Transaction data is simulated.** No public labelled UPI fraud dataset exists.
2. **The coercion corpus is templated**, not collected from real scam traffic.
3. **UPI ID existence is not verified** unless a provider is configured. Format and PSP handle
   are checked locally and free; whether the account exists can only be answered by the payment
   network. This is a configured seam (`UPI_VERIFY_URL`), not a stub — and nothing anywhere
   reports an address as verified unless a provider actually said so.
4. **The payee graph is only as good as its population.** A cold-start deployment has no
   history, so stream 3 contributes nothing until payers accumulate.
5. **Social-engineering recall is 28.6%**, by far the lowest of the four fraud types. That is
   the honest headline for the case the project is about.
6. **71.4% of social engineering is still missed** by the transaction model. Streams 5 and 6
   exist to attack that, and they are the project's original contribution, but they depend on
   the payer volunteering the message and the purpose.
7. **A large legitimate payment has roughly a 7% chance of being warned**, against 0.83% for
   everyday amounts. The 1% false-positive budget is an average; large payments carry more of
   it.
8. **The ₹1 lakh cap is a configured constant, not a live lookup.** NPCI revises these limits
   and individual banks set lower ones. `UPI_MAX_AMOUNT` and `UPI_MAX_AMOUNT_MERCHANT` exist
   so the number can be corrected without a code change.
7. **`risk_model.pkl` is not portable.** A pickle is tied to the library versions that produced
   it. It is gitignored on purpose. Run `python backend/train_model.py` on the machine that
   will serve it. The coercion model uses JSON weights specifically so it *is* portable, and it
   reproduces bit-for-bit across numpy versions.

---

## 7. Reproducing everything

```bash
pip install -r requirements.txt

python scripts/build_coercion_corpus.py     # 1,022 messages
python backend/ml/coercion_model.py         # -> models/coercion_weights.json
python backend/train_model.py               # -> risk_model.pkl, metrics.json, shap_background.json
python -m pytest -q                         # 202 passed

# repair statement rows written by the older parsers
python scripts/rebuild_profiles.py report
python scripts/rebuild_profiles.py all
```

Run the trainer on **your** machine. The metrics in §4 were produced on numpy 2.4.4 /
scikit-learn 1.8.0; yours will differ in the last digits and the threshold will move slightly.
That is expected — the operating point is chosen from your own validation split.

---

## 8. Still outstanding

Two items, neither of which I can do for you:

1. **Rotate the Postgres password.** It is in the git history of
   `github.com/murali-N-tech/pay`. Rotating it is your action — I have deliberately not
   touched credentials, and rewriting the history would need a force-push over work already
   on the remote. See §5.0b: the only code that ever used that database is dead, so deleting
   two files removes the reason it exists.

2. **Redeploy the Python backend to Render.** `vercel.json` points at
   `edge-upi-backend.onrender.com`, which is still running the **pre-audit** code — including
   the six unauthenticated endpoints in §5.2. Until it is redeployed, that deployment leaks
   every user's payment amounts to anyone who asks. This is the most urgent item in this
   report.

Also pending, and mechanical: committing this audit and merging with `origin/main` (`-s ours`
for the deployment-file divergence). I could not reach your machine at the end of this session,
so the changed files are attached as a bundle.

---

## 9. What to say in the viva

The project's strongest claim is not an accuracy number. It is this:

> Payer-behaviour modelling and payee-graph analysis together catch 28.6% of
> social-engineering fraud. Alone, neither reaches 9% — the two together are worth more than
> their sum. The remaining 71.4% is not missed for want of a better model: it is missed
> structurally, because in payer-authorised fraud the evidence is not in the transaction. It
> is in the instruction that produced it, and in the gap between what the payer believes they
> are paying for and who actually receives the money. That is what streams 5 and 6 read, and
> no UPI app reads them today.

And the second-strongest claim is that every number in §4 survived an audit that found the
first version of them was measuring a leak, and the second version was measuring a population
in which no one paid rent. The figures are lower than the ones this project started with. They
are the ones that will hold up.
