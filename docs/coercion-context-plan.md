# Coercion-Context Scoring — design and evaluation plan

**Project:** Edge AI UPI Behavioural Risk Intelligence System
**Proposed addition:** a third evidence stream — the *pressure the payer is under* — fused with the existing payer-behaviour and payee-graph signals.
**Scope of this plan:** the smallest version that genuinely works and can be honestly measured in one working session.

---

## 1. Why this, and not something else

Two of the obvious "next features" are already taken, and a viva panel that follows the field will know it:

| Already shipped | By whom | Overlaps with |
|---|---|---|
| Cross-bank mule detection, network-wide account flagging | RBI **DPIP**, launched 2025, banks integrating through late 2025 | your fan-in / payee-reputation work |
| On-device scam detection during **calls**; warning when screen-sharing with a payment app open | Google, India, Nov 2025 — Pixel-only, English-only | nothing of yours yet |
| Payee name display, "first time you're paying this person" | GPay / PhonePe | your first-payment signal |

What none of them do: **score the message that caused the payment, at the moment of payment, and explain it to the person about to pay.** DPIP watches accounts from the bank side. Google watches call audio, on one phone brand. The payer, mid-scam, is told nothing.

The project's own measurements say this is where the loss is:

| signals used | social-engineering recall @ 1% FPR |
|---|---|
| payer behaviour only | 36.2% |
| payee signals only | 22.6% |
| payer + payee | 58.4% |

Around 40% of social-engineering fraud is still missed, and it is missed *for a reason*: in that fraud class the payer is behaving normally by definition — they were persuaded. The decisive evidence is not in the transaction. It is in the conversation that produced the transaction.

**Claim to defend:** adding the coercion context is not another feature column. It is the only stream that can see this fraud class at all.

---

## 2. What the feature is

Three new inputs, collected at payment time.

**a. The trigger message** — *opt-in.* The user pastes the SMS/WhatsApp/email that led them here. Never read automatically, never stored raw.

**b. Stated intent** — one tap: `bill · shop · friend · refund · investment · someone asked me to`.

**c. Interaction telemetry** — already half-built in `backend/app/services/behavioral_biometrics.py`, currently unused: was the VPA typed, pasted, or scanned; time from opening to submitting; did the session start from a link.

### The persuasion features

The message is reduced to **named, inspectable patterns**, not a black-box score:

| pattern | what it looks for |
|---|---|
| `authority` | claims to be bank / police / KYC / officer / government |
| `urgency` | deadline, "within N minutes", "immediately", "last warning" |
| `fear` | account block, penalty, arrest, legal action |
| `secrecy` | "do not tell", "do not discuss with anyone" |
| `lure` | refund, prize, cashback, lottery, job advance |
| `remote_control` | install app, screen share, AnyDesk / TeamViewer |
| `verify_payment` | "pay ₹1 to verify", "small amount to confirm" |
| `brand_vpa_mismatch` | message claims a brand; the VPA belongs to someone else |

Each is a separate feature with its own precision. That matters more than accuracy: the explanation is the product.

### The fusion — where the value actually is

No single stream should reach BLOCK on its own. The contribution is **contradiction detection across streams**:

> You said this is an **electricity bill**.
> The address is an **individual's UPI ID** that **41 people have paid exactly once**.
> The message uses **bank authority**, a **30-minute deadline**, and asks you **not to discuss it**.
>
> **BLOCK** — three independent streams agree, and the stated intent contradicts the payee.

Reuse the existing combiner in `payee_check.py` — strongest signal, plus 0.4× the rest — and add an **agreement bonus** only when streams from *different* families concur. Two urgency words in one message must never do what one urgency word plus a mule-shaped payee does.

---

## 3. Smallest real version (one session)

**In scope**

1. `backend/app/services/coercion.py` — pattern extractors, one function per pattern, each returning a matched span so the UI can quote it.
2. A small **logistic regression** over the pattern features. Interpretable, trains in seconds, coefficients readable in the report. *Not* a transformer — see §6.
3. `intent` and `message` accepted by the existing `/payee/check` endpoint, both optional. Everything keeps working when they are absent.
4. Fusion in `payee_check.py`, including the intent-vs-payee contradiction rule.
5. UI: an optional "Why are you paying?" step on the payee-check page, and the quoted spans shown in the verdict.
6. A labelled corpus and the evaluation in §5.
7. Tests, including the hard negatives.

**Explicitly out of scope** — say so in the report rather than implying otherwise:

- Reading messages automatically from the device. Opt-in paste only.
- Transformer fine-tuning, embeddings, or an LLM call in the payment path.
- Languages other than English and romanised Hindi.
- Voice/call analysis.
- Storing message text anywhere.

---

## 4. The dataset — and the trap in it

The corpus has to be built, and **how it is built determines whether the result means anything.**

| class | source | approximate size |
|---|---|---|
| scam messages | public smishing/phishing corpora + synthetic Indian UPI scripts written from documented scam patterns | 400–600 |
| **hard negatives** | *legitimate* bank/merchant/utility SMS that also use urgency, authority and deadlines | 400–600 |
| easy negatives | ordinary personal and transactional messages | 200 |

**The hard negatives are the entire experiment.** Real bank messages say "urgent", "your account will be blocked", "act immediately", "verify now". A detector that flags urgency will score beautifully against easy negatives and be useless — and worse, it will cry wolf on genuine bank alerts, training users to ignore it.

This is the same failure the project already caught once: the first simulator gave PR-AUC 0.9949, which was a red flag rather than a result, and rebuilding it harder brought it to 0.62. Apply that lesson here from the start. **If the hard-negative false-positive rate is not reported, the number is not a result.**

---

## 5. Evaluation

Report all four, not just the last:

1. **Per-pattern precision and recall** on held-out messages. Which patterns are trustworthy and which are noise.
2. **False-positive rate on hard negatives specifically**, reported separately from overall FPR. The headline safety number.
3. **The fourth ablation row** — the contribution:

   | signals used | social-engineering recall @ 1% FPR |
   |---|---|
   | payer only | 36.2% |
   | payee only | 22.6% |
   | payer + payee | 58.4% |
   | payer + payee + **coercion context** | *to be measured* |

4. **Decision changes.** How many transactions moved between APPROVE / WARN / STEP-UP / BLOCK, and in which direction. A feature that changes no decisions is not a feature.

**How this could fail, stated in advance:** if the lift over payer+payee is small, or the hard-negative FPR is high, the honest conclusion is that lexical patterns are insufficient and the problem needs semantics. That is a legitimate finding and defensible in a viva. Reporting a good number produced by easy negatives is not.

---

## 6. Why a lexicon plus logistic regression, not a transformer

Not a shortcut — a defensible choice, and worth saying out loud to your guide:

- **Explainability is the product.** "This message uses bank authority and a 30-minute deadline" is actionable. A 0.83 from DistilBERT is not, and the whole project's stance is that a score without a reason is not a decision.
- **It runs in the payment path**, on a phone, in milliseconds, offline.
- **A transformer on ~1,200 mostly-synthetic messages** would memorise the generator, not learn the phenomenon — and the resulting number would be the 0.9949 mistake again.
- The **fusion across three streams** is the contribution. The text model is one input to it.

If a transformer baseline is wanted, add it as a *comparison row*, honestly labelled as trained on synthetic data.

---

## 7. Privacy and ethics — non-negotiable

- Paste is opt-in and skippable; the check works without it and says so.
- Message text is scored in memory and **discarded**. Only the extracted pattern flags are kept, if anything is.
- The verdict is decision support for the payer, never an accusation about the payee. Existing wording rules stay: nothing claims verification that did not happen.
- No message content leaves the device in the mobile build.

---

## 8. What to tell your guide

> The system currently scores the payer's behaviour and the payee's graph position. Measured on our own data, that catches 58.4% of social-engineering fraud at a 1% false-positive budget. The remaining 40% is missed structurally: in that fraud class the payer behaves normally because they were persuaded, so the evidence is not in the transaction.
>
> We add a third stream — the coercion context: the message that prompted the payment, the payer's stated intent, and how they entered the address. The contribution is the fusion: a payment is blocked when independent streams agree and the stated intent contradicts the payee, not when any one of them fires.
>
> RBI's DPIP does this from the bank side, after the fact, and does not explain anything to the payer. Google's on-device scam detection covers calls, on Pixel devices, in English. Nothing scores the message at the moment of payment and tells the person why to stop.

---

## 9. Sequence for the session

1. Pattern extractors + tests (each pattern with its own positive and hard-negative cases).
2. Corpus assembly, hard negatives written **first** so the patterns are not tuned to easy wins.
3. Logistic model, per-pattern metrics, hard-negative FPR.
4. Fusion + contradiction rule in `payee_check.py`; endpoint accepts `intent` and `message`.
5. Re-run the ablation; add the fourth row to `models/metrics.json`.
6. UI step and quoted spans.
7. README section, honest about the synthetic corpus.

The demo exists after step 4; steps 5–7 make it defensible.

---

## 10. Open questions for you

1. **English only, or English + romanised Hindi?** Romanised Hindi ("turant", "band ho jayega") roughly doubles the corpus work and is much closer to real Indian scam traffic.
2. **Is the paste step acceptable in your demo?** If a live paste feels awkward in a viva, the alternative is three preloaded example scenarios — but the paste is what makes the point land.
3. **Do you want the transformer comparison row**, or is the interpretable model alone the right story for your evaluation?
