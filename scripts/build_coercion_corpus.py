"""Build the labelled message corpus for the coercion detector.

READ THIS BEFORE TRUSTING ANY NUMBER PRODUCED FROM IT
-----------------------------------------------------
The hard negatives are written FIRST, on purpose, and they are the entire
experiment. A real bank SMS says "urgent", "your account will be blocked",
"verify immediately" - exactly the words a naive scam detector keys on. A
detector evaluated only against chatty personal messages will score beautifully
and be actively harmful in production, because it fires on genuine bank alerts
and trains people to dismiss the warning.

This project has already made the equivalent mistake once: the first fraud
simulator produced PR-AUC 0.9949, which was a red flag rather than a result.
Rebuilding it to be hard brought it to 0.62 and made it mean something.

So: roughly as many hard negatives as scams, every hard negative containing at
least one term the weak patterns fire on, and the false-positive rate on hard
negatives reported separately as the headline safety number.

LIMITS, to be stated wherever these numbers appear
--------------------------------------------------
Templated, not collected from real scam traffic. It shows whether the METHOD
can separate persuasion structure from legitimate urgency. It does not
establish field performance, and no claim of field performance should be made
from it.

    python scripts/build_coercion_corpus.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

OUT = Path("data") / "coercion_corpus.jsonl"
SEED = 42

# ── Hard negatives: legitimate, and deliberately loaded with the weak cues ────
# Every one of these contains authority, urgency or fear terms. If the detector
# leans on those, it fails here - which is the point.

HARD_NEGATIVE_TEMPLATES = [
    "Dear Customer, your {bank} account XX{n4} has been debited by Rs {amt} on {date}. If this was not you, report immediately on the number printed on your card.",
    "{bank}: Your KYC is due for periodic update. Please visit your nearest branch before {date} to avoid restrictions on your account. Do not share your OTP with anyone.",
    "Urgent: Your {bank} debit card ending {n4} will be blocked for international use from {date} unless you enable it in the app.",
    "Dear Customer, an amount of Rs {amt} is due on your {bank} credit card by {date}. Late payment attracts a penalty and affects your credit score.",
    "{bank} Alert: A login to your net banking from a new device was detected. If this was not you, call the helpline on the back of your card immediately.",
    "Your electricity bill of Rs {amt} for consumer number {n8} is due on {date}. Pay through the official portal to avoid disconnection.",
    "Income Tax Department: Your return for AY 2025-26 has been processed. Any refund will be credited to your pre-validated bank account. No action is required.",
    "{bank}: Rs {amt} credited to your account XX{n4} on {date}. Available balance Rs {amt2}.",
    "Reminder: Your insurance policy {n8} lapses on {date}. Renew via the official app or branch. Our staff will never ask for your PIN or OTP.",
    "{bank} Alert: Your account XX{n4} has insufficient balance for the standing instruction due on {date}. Please maintain balance to avoid a failure charge.",
    "Your gas connection subsidy of Rs {amt} has been credited by the government to your registered bank account on {date}.",
    "{bank}: Cheque number {n6} issued on your account has been returned unpaid. Penalty charges as applicable will be levied. Contact your branch.",
    "Traffic Police: An e-challan of Rs {amt} has been issued against vehicle number registered to you. Pay only through the official state transport portal.",
    "{bank} net banking will be unavailable on {date} from 1 AM to 4 AM for scheduled maintenance. We regret the inconvenience.",
    "Urgent reminder: your loan EMI of Rs {amt} is overdue. Please clear the outstanding immediately to avoid legal action and reporting to the credit bureau.",
    "Your mobile number will be deactivated in 24 hours as the address verification is pending. Visit the official store with your ID. We never ask for OTP over a call.",
    "{bank}: Your fixed deposit {n8} matures on {date}. If no instruction is received it will auto-renew at the prevailing rate.",
    "Customs notification: A parcel addressed to you is held pending documentation. Track the status only on the official portal using your consignment number.",
    "{bank}: Your request to update your registered email has been received and will be effective within 24 hours. If this was not you, contact us urgently.",
    "Court notice: Hearing in case number {n6} is scheduled on {date}. Please be present. This message is for information only.",
]

# Legitimate messages that USE the strong patterns. Without these the task is
# trivially separable and every number from it is meaningless: real merchants
# ask you to pay, real banks give you a helpline to call, real offers include
# cashback, real loans charge a processing fee, and real support asks you to
# install their app. If the detector cannot tell these from a scam, it does
# not work - and finding that out here is the entire point of the corpus.

HARD_NEGATIVE_TEMPLATES += [
    "Your {bank} credit card bill of Rs {amt} is due on {date}. Pay now through the official app to avoid late fees.",
    "Reminder: pay your broadband bill of Rs {amt} before {date} to keep the service active. Pay in the app or at any authorised centre.",
    "You have earned Rs {amt} cashback on your last transaction. It will be credited to your wallet within 3 working days.",
    "Your loan application {n8} is approved. A one time processing fee of Rs {amt} will be deducted from the disbursed amount as per the sanction letter.",
    "For any issue with this transaction, call our helpline number {phone} between 9 AM and 6 PM. We will never ask for your OTP, PIN or CVV.",
    "Install the official {bank} app from the Play Store to manage your account. Do not download the app from links sent by anyone.",
    "Your refund of Rs {amt} for the cancelled order has been initiated and will reflect in 5-7 working days. No action is required from you.",
    "Dear customer, please pay the outstanding amount of Rs {amt} urgently to avoid disconnection of your electricity connection.",
    "Your policy renewal premium of Rs {amt} is due. Pay now via the official portal. Our staff will never ask you to share your PIN or password.",
    "This message contains confidential account information intended only for you. Do not share it with anyone, including anyone claiming to be from the bank.",
    "Congratulations, you have won a Rs {amt} voucher in our festive draw. Claim it in the Offers section of the app. We will never ask for a fee.",
    "Your {bank} account statement for {date} is ready. To request a physical copy, call this number {phone} or visit your branch.",
    "Scan the QR at the counter to pay Rs {amt}. Always check the merchant name shown by your UPI app before you confirm.",
    "Your KYC update is complete. No fee was charged. If anyone asks you to pay for KYC, it is a scam - report it.",
    "Support ticket {n6} has been created for your complaint. Our executive will call you on your registered number. We will never ask you to share your screen.",
]

# ── Easy negatives: ordinary traffic ─────────────────────────────────────────

EASY_NEGATIVE_TEMPLATES = [
    "Hey, I have sent you Rs {amt} for the dinner yesterday. Check once.",
    "Amma, please send Rs {amt} when you can, hostel mess fee is due this week.",
    "Your order {n8} has been shipped and will be delivered by {date}. Track it in the app.",
    "Team, standup moved to 10:30 tomorrow. Please update the sheet before that.",
    "Your cab is arriving in 3 minutes. Vehicle number and driver details are in the app.",
    "Happy birthday da! Party kab hai?",
    "Table for 4 confirmed at {date} 8 PM. See you then.",
    "Your appointment with Dr. Rao is confirmed for {date} at 5 PM. Please arrive 10 minutes early.",
    "Rent for this month sent, Rs {amt}. Let me know if you got it.",
    "Class rescheduled to Friday. Bring the lab record.",
    "I will transfer the Rs {amt} tonight after my salary comes in.",
    "Your recharge of Rs {amt} was successful. Validity till {date}.",
]

# ── Scams ─────────────────────────────────────────────────────────────────────
# Written to carry persuasion STRUCTURE - a request to act, plus a reason you
# must act now, plus a channel - rather than any single give-away word.

SCAM_TEMPLATES = [
    "Dear customer, your {bank} account will be blocked today as KYC is pending. Complete verification urgently by paying a refundable fee of Rs 10 to {vpa} or call this number {phone}.",
    "Congratulations! You are a lucky winner of Rs {big} cashback. To claim, pay a processing fee of Rs {amt} to {vpa} within 30 minutes.",
    "This is officer from cyber cell. A case will be filed against your account. Do not discuss this with anyone. Transfer Rs {big} to {vpa} for verification of funds.",
    "Sir, I am from {bank}. To restore your account please install AnyDesk and share your screen so we can complete the process. Do not share this with family members.",
    "Your electricity connection will be disconnected tonight as the bill is unpaid. Pay immediately to {vpa} or call this number {phone} to avoid disconnection.",
    "Your parcel is held at customs. Pay a clearance fee of Rs {amt} to {vpa} today, otherwise legal action will be taken.",
    "Aapka {bank} account band ho jayega. Turant Rs {amt} bhejo is UPI par {vpa}. Kisi ko mat batao.",
    "Work from home opportunity! Earn Rs {big} per week. Pay a one time registration fee of Rs {amt} to {vpa} to get started today.",
    "I am your manager. I am in a meeting and cannot talk. Urgently transfer Rs {big} to {vpa} for a client payment. Do not discuss this with the team, I will reimburse you.",
    "Refund of Rs {big} is approved for your cancelled booking. Download the app from this link and share your screen so our executive can process the refund.",
    "Your UPI PIN has expired. To reactivate, send Rs 1 to {vpa} for verification. Failure to do so will deactivate your account within 24 hours.",
    "Investment plan with guaranteed returns of 40 percent. Limited seats. Transfer the token amount of Rs {amt} to {vpa} today, offer expires today.",
    "Army officer posted here, need to sell my furniture urgently before transfer. Pay advance Rs {amt} to {vpa} and I will arrange delivery. Please hurry, others are interested.",
    "Your SIM will be deactivated for pending verification. Call this number {phone} immediately and share the OTP sent to your phone to keep the number active.",
    "{bank} security alert: unusual login detected. To secure your account, transfer your balance to the safe account {vpa} provided by our officer. Do not inform anyone.",
    "You have received Rs {big} by mistake from my account. Please return the amount to {vpa} immediately or I will file an FIR against you.",
    "Final notice from income tax department. Penalty of Rs {big} is due. Pay now to {vpa} to avoid arrest. This is your last warning.",
    "Hi, this is your daughter, my phone broke and this is my new number. Please transfer Rs {amt} to {vpa} urgently, I will explain later. Do not tell papa.",
    "Complete your KYC in the app. Scan this QR to verify your identity. The amount will be refunded within 24 hours. Activation fee Rs {amt}.",
    "Your loan is pre-approved. To release the amount, pay the processing fee of Rs {amt} to {vpa}. Offer valid only today, call me on {phone}.",
]

BANKS = ["SBI", "HDFC Bank", "ICICI Bank", "Axis Bank", "Kotak Bank", "PNB", "Bank of Baroda"]
VPAS = ["refund.help@okaxis", "9812345678@upi", "kyc-verify@ybl", "support1122@paytm",
        "quickcash@okhdfcbank", "verify.now@okicici"]


def _fill(template: str, rng: random.Random) -> str:
    return (
        template
        .replace("{bank}", rng.choice(BANKS))
        .replace("{vpa}", rng.choice(VPAS))
        .replace("{phone}", f"9{rng.randint(100000000, 999999999)}")
        .replace("{n4}", str(rng.randint(1000, 9999)))
        .replace("{n6}", str(rng.randint(100000, 999999)))
        .replace("{n8}", str(rng.randint(10000000, 99999999)))
        .replace("{amt2}", f"{rng.randint(500, 90000):,}")
        .replace("{amt}", f"{rng.choice([49, 99, 199, 250, 499, 999, 1450, 2300]):,}")
        .replace("{big}", f"{rng.choice([25000, 45000, 60000, 125000, 250000]):,}")
        .replace("{date}", f"{rng.randint(1, 28):02d}-{rng.randint(1, 12):02d}-2026")
    )


def build(seed: int = SEED) -> list[dict]:
    rng = random.Random(seed)
    rows: list[dict] = []

    def add(templates: list[str], label: int, kind: str, copies: int) -> None:
        for template in templates:
            for _ in range(copies):
                rows.append({"text": _fill(template, rng), "label": label, "kind": kind})

    # Hard negatives first, and at least as many as the scams.
    add(HARD_NEGATIVE_TEMPLATES, 0, "hard_negative", 25)   # 500
    add(SCAM_TEMPLATES, 1, "scam", 25)                     # 500
    add(EASY_NEGATIVE_TEMPLATES, 0, "easy_negative", 17)   # 204

    # De-duplicate: templated fill can collide, and duplicates across the
    # train/test split would inflate every number reported from it.
    seen: set[str] = set()
    unique = []
    for row in rows:
        if row["text"] in seen:
            continue
        seen.add(row["text"])
        unique.append(row)

    rng.shuffle(unique)
    return unique


def main() -> None:
    rows = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1

    print(f"  wrote {OUT}  ({len(rows)} unique messages after de-duplication)")
    for kind, n in sorted(counts.items()):
        print(f"    {kind:16} {n:>4}")
    print("\n  Templated, not collected from real scam traffic. Any number produced")
    print("  from this corpus measures the method, not field performance.")


if __name__ == "__main__":
    main()
