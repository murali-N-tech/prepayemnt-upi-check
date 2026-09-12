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

**The single most important finding**: the training data was leaking the label. One feature,
`payee_distinct_payers`, was a whole number for every legitimate row and a fraction for
99.6% of fraud rows. A single decision-tree split on "is this a whole number?" separated the
classes perfectly. Every accuracy figure the project reported was measuring that artefact.
The honest figures, after the fix, are in §4.

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

**Data**: 120,000 simulated transactions, 1.19% fraud. 72,000 train / 18,000 validation /
30,000 test (355 fraud rows in test).

| Metric | Logistic baseline | **Selected: HistGradientBoosting** |
|---|---|---|
| ROC-AUC | 0.9503 | **0.9815** |
| PR-AUC | 0.1801 | **0.6187** |
| Recall @ 1% FPR budget | 23.7% | **67.6%** |
| Realised FPR on test | 1.04% | **0.83%** |
| Precision at that point | 21.4% | **49.3%** |
| Brier | 0.01045 | **0.0067** |

Brier alone is meaningless, so the reference is reported beside it: always predicting the
base rate scores **0.01169**, which makes the selected model's **Brier skill score +0.427** —
it removes 43% of the reference error. Say that, not "Brier 0.0067, which is very low".

**Recall by fraud type**, at the same 1% false-positive budget:

| Scenario | n | Recall |
|---|---|---|
| Card testing (tiny probe payments) | 24 | 95.8% |
| Mule collection | 71 | 74.7% |
| Account takeover | 82 | 73.2% |
| **Social engineering** (payer authorised it) | 178 | **58.4%** |

Unsupervised half: IsolationForest fitted on legitimate traffic only, ROC-AUC 0.871.

### 4.1 The ablation, stated correctly

The project's original claim was: *a model that sees only the payer's behaviour cannot catch
social engineering, because the payer is behaving normally by definition.* The numbers do
**not** support that claim, and the training script used to print the claim unconditionally
whatever the numbers said. It now reads them.

Social-engineering recall:

| Feature set | Recall |
|---|---|
| Payer behaviour only | 36.5% |
| Payee signals only | 24.2% |
| **Both** | **58.4%** |

The payer half is *not* blind to this case here, because in the simulator half of
social-engineering payments are a large multiple of the victim's usual amount — real scam
amounts sometimes are. So the defensible claim is the **combined lift: +21.9 points over the
better single half.** Neither half alone reaches what both reach together. Report that, and
say why streams 5 and 6 (stated purpose, message pressure) exist: the remaining 41.6% is
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

175 tests pass, including 27 new regression tests written specifically to pin these down.
Everything below was verified by execution before and after the fix, not by inspection.

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
5. **Social-engineering recall is 58.4%**, the lowest of the four fraud types. That is the
   honest headline for the case the project is about.
6. **41.6% of social engineering is still missed.** Streams 5 and 6 exist to attack that, and
   they are the project's original contribution, but they depend on the payer volunteering the
   message and the purpose.
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
python -m pytest -q                         # 175 passed

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
   on the remote.

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

> Payer-behaviour modelling and payee-graph analysis together catch 58.4% of
> social-engineering fraud. Neither half alone exceeds 36.5%. The remaining 41.6% is not
> missed for want of a better model — it is missed structurally, because in payer-authorised
> fraud the evidence is not in the transaction. It is in the instruction that produced it, and
> in the gap between what the payer believes they are paying for and who actually receives the
> money. That is what streams 5 and 6 read, and no UPI app reads them today.

And the second-strongest claim is that every number in §4 survived an audit that found the
first version of them was measuring a leak.
