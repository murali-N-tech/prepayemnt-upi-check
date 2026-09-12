"""Regressions for the parser bugs found in the full-project audit.

Each test here failed before the fix it names. They are written against the
smallest unit that shows the bug so a future change that reintroduces it fails
loudly rather than quietly producing wrong numbers.
"""

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

import pandas as pd
import pytest

from backend.app.services.statement_parser import (
    _build_provider_blocks,
    _extract_amount_from_line,
    _extract_bhim_transactions,
    _extract_google_pay_transactions,
    _extract_paytm_transactions,
    _extract_phonepe_transactions,
    _has_clock,
    _transaction_from_bank_line,
    generate_behavior_profile,
)


# ── A transaction id is not an amount ────────────────────────────────────────

@pytest.mark.parametrize(
    "line",
    [
        "PhonePe Transaction ID: PP123456789",
        "UTR: 123456789012",
        "Google transaction ID: 987654321",
        "UPI Ref No 445566778899",
    ],
)
def test_a_reference_number_is_never_read_as_an_amount(line):
    """The scorer penalised reference-like numbers but returned the best
    candidate however negative its score, so a transaction id came back as an
    amount of Rs 123,456,789 - which then became the user's max_amount and the
    denominator of every amount ratio."""
    assert _extract_amount_from_line(line) is None


@pytest.mark.parametrize(
    "line,expected",
    [
        ("INR 420.00", 420.0),
        ("Amount INR 850.00", 850.0),
        ("420.00", 420.0),
        ("1200", 1200.0),
        ("UTR: 123456789012 | INR 420.00 | SUCCESS", 420.0),
        ("01/06/2026 UPI/SWIGGY/123456 420.00 5000.00", 420.0),
    ],
)
def test_the_floor_does_not_reject_real_amounts(line, expected):
    assert _extract_amount_from_line(line) == expected


# ── One wallet record is one block ───────────────────────────────────────────

PHONEPE_LINES = [
    "PhonePe Transaction Statement",
    "01 Jun 2026",
    "09:12 AM",
    "Paid to Swiggy",
    "swiggy@ibl",
    "PhonePe Transaction ID: PP123456789",
    "UTR: 123456789012",
    "INR 420.00",
    "SUCCESS",
]


def test_a_wallet_record_is_not_split_into_one_block_per_line():
    """The keyword lists contain "to", "from" and "utr", and a keyword match was
    treated as a record boundary, so a single PhonePe transaction became five
    blocks - none of which held both a date and an amount."""
    blocks = _build_provider_blocks(
        PHONEPE_LINES,
        (("phonepe", "paid to", "utr", "transaction id", "to", "from"),),
    )
    assert len(blocks) == 1
    joined = " ".join(blocks[0])
    assert "01 Jun 2026" in joined
    assert "420.00" in joined


@pytest.mark.parametrize(
    "extractor,lines,amount,merchant",
    [
        (_extract_phonepe_transactions, PHONEPE_LINES, 420.0, "Swiggy"),
        (
            _extract_google_pay_transactions,
            [
                "Google Pay statement",
                "02 Jun 2026 10:45 PM",
                "Paid to Amazon Pay",
                "amazonpay@apl",
                "Google transaction ID: 987654321ABC",
                "Amount INR 850.00",
                "Completed",
            ],
            850.0,
            "Amazon Pay",
        ),
        (
            _extract_paytm_transactions,
            [
                "Paytm Payments Bank Statement",
                "03 Jun 2026",
                "07:30 PM",
                "Paid to Jio Recharge",
                "jio@paytm",
                "UPI Ref No: 555566667777",
                "Rs 299.00",
                "SUCCESS",
            ],
            299.0,
            "Jio Recharge",
        ),
        (
            _extract_bhim_transactions,
            [
                "BHIM UPI history",
                "04 Jun 2026",
                "08:05 PM",
                "Paid to Flipkart",
                "flipkart@axis",
                "Txn ID: BHIM123456",
                "UTR: 444455556666",
                "INR 1200.00",
                "SUCCESS",
            ],
            1200.0,
            "Flipkart",
        ),
    ],
)
def test_every_wallet_extractor_returns_the_transaction(extractor, lines, amount, merchant):
    """All four of these returned [] for every statement in this layout, which
    is four of the nine supported providers."""
    txns = extractor(lines, "\n".join(lines))
    assert len(txns) == 1, f"{extractor.__name__} extracted nothing"
    assert txns[0]["amount"] == amount
    assert merchant.lower() in str(txns[0]["merchant"]).lower()


# ── txn_type and time_known on every return path ─────────────────────────────

def test_a_bank_line_reports_its_direction_and_whether_it_had_a_time():
    """profile_store defaults a missing txn_type to DEBIT and a missing
    time_known to 1, so a credit joined the spending average and a date-only row
    became a genuine midnight payment. Four of the five pypdf return sites
    omitted both keys."""
    credit = _transaction_from_bank_line(
        "05/06/2026 NEFT credited from ACME PAYROLL 45000.00 51200.00", "HDFC"
    )
    assert credit is not None
    assert credit["txn_type"] == "CREDIT"
    assert credit["time_known"] is False

    debit = _transaction_from_bank_line(
        "05/06/2026 14:22 UPI paid to swiggy@ibl 420.00 6200.00", "HDFC"
    )
    assert debit is not None
    assert debit["txn_type"] == "DEBIT"
    assert debit["time_known"] is True


def test_has_clock_only_accepts_a_real_clock():
    assert _has_clock("01/02/2024 14:30 paid to x") is True
    assert _has_clock("01/02/2024 paid to x") is False
    assert _has_clock("") is False
    assert _has_clock(None) is False


# ── The night ratio's denominator ────────────────────────────────────────────

def test_the_profile_reports_how_many_rows_the_hour_statistics_used():
    """night_transactions is counted over rows with a real clock time, so the
    UI needs that count as its denominator. Dividing by transaction_count
    halved the reported night ratio on a statement where half the rows print no
    time."""
    rows = []
    # Four real night payments, with times.
    for day in range(1, 5):
        rows.append({
            "timestamp": f"2026-06-0{day}T02:30:00", "amount": 100.0,
            "merchant": "SHOP", "upi_id": "shop@ybl", "status": "SUCCESS",
            "txn_type": "DEBIT", "time_known": True,
        })
    # Four date-only rows, which parse to midnight but are not night payments.
    for day in range(5, 9):
        rows.append({
            "timestamp": f"2026-06-0{day}T00:00:00", "amount": 100.0,
            "merchant": "SHOP", "upi_id": "shop@ybl", "status": "SUCCESS",
            "txn_type": "DEBIT", "time_known": False,
        })

    p = generate_behavior_profile(rows)
    assert p["transaction_count"] == 8
    assert p["timed_transaction_count"] == 4
    assert p["night_transactions"] == 4
    # The true night ratio is 4/4, not 4/8.
    assert p["night_transactions"] / p["timed_transaction_count"] == 1.0
    assert p["transactions_without_time"] == 4


def test_distinct_payees_is_not_capped_at_the_top_ten():
    """merchant_frequency is deliberately the top 10, and the UI read
    len(merchant_frequency) as "unique payees" - a number that could never
    exceed 10 however many payees the statement held."""
    rows = [
        {
            "timestamp": f"2026-06-01T1{i % 10}:00:00", "amount": 100.0 + i,
            "merchant": f"SHOP {i}", "upi_id": f"shop{i}@ybl", "status": "SUCCESS",
            "txn_type": "DEBIT", "time_known": True,
        }
        for i in range(25)
    ]
    p = generate_behavior_profile(rows)
    assert len(p["merchant_frequency"]) == 10
    assert p["distinct_payees"] == 25
