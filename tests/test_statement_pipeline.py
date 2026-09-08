"""Regression tests for the four bugs that corrupted behaviour profiles.

Each test here fails against the code as it was before the audit fixes.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.app.services.statement_parser import (
    _looks_like_header,
    _normalize_timestamp,
    _parse_clock,
    _parse_csv_statement,
    generate_behavior_profile,
)

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample_upi_statement.csv"


# ── C1: the CSV parser dropped the time column ────────────────────────────

def test_csv_parser_keeps_the_time_column():
    txs = _parse_csv_statement(SAMPLE.read_bytes())
    hours = {t["timestamp"][11:13] for t in txs}
    assert hours != {"00"}, "every transaction landed at midnight - the time column was dropped"
    assert "09" in hours and "13" in hours


def test_profile_hours_are_not_a_constant():
    profile = generate_behavior_profile(_parse_csv_statement(SAMPLE.read_bytes()))
    assert profile["most_active_hour"] != 0
    assert profile["night_transactions"] < profile["transaction_count"], \
        "all ten sample transactions were classified as night transactions"
    assert len(profile["hourly_distribution"]) > 1


# ── C1b: ISO timestamps had month and day swapped ─────────────────────────

def test_iso_timestamp_is_not_reparsed_dayfirst():
    # 2026-04-01 is the 1st of April. dayfirst=True turned it into 4 January.
    assert _normalize_timestamp("2026-04-01T12:00:00").startswith("2026-04-01")


def test_ambiguous_dates_are_still_day_first():
    assert _normalize_timestamp("01/04/2026").startswith("2026-04-01")


@pytest.mark.parametrize(
    "raw,expected",
    [("03:33PM", "15:33:00"), ("11:05 PM", "23:05:00"), ("15:33", "15:33:00"), ("nonsense", None)],
)
def test_clock_parsing(raw, expected):
    assert _parse_clock(raw) == expected


# ── C2: credits were counted as spending ──────────────────────────────────

def test_credits_do_not_move_the_spending_baseline():
    debits = [
        {"timestamp": "2026-06-01T10:00:00", "amount": 400.0, "merchant": "Swiggy",
         "upi_id": "", "status": "SUCCESS", "reference_number": "1", "txn_type": "DEBIT"},
        {"timestamp": "2026-06-02T11:00:00", "amount": 600.0, "merchant": "Zomato",
         "upi_id": "", "status": "SUCCESS", "reference_number": "2", "txn_type": "DEBIT"},
    ]
    salary = {"timestamp": "2026-06-03T09:00:00", "amount": 50000.0, "merchant": "PAYROLL",
              "upi_id": "", "status": "SUCCESS", "reference_number": "3", "txn_type": "CREDIT"}

    before = generate_behavior_profile(debits)
    after = generate_behavior_profile(debits + [salary])

    assert after["max_amount"] == before["max_amount"] == 600.0
    assert after["avg_amount"] == before["avg_amount"] == 500.0
    assert after["credit_count"] == 1 and after["debit_count"] == 2
    assert "PAYROLL" not in after["favorite_merchants"]


# ── C3: page headers were stored as transactions ──────────────────────────

@pytest.mark.parametrize("line", [
    "Sent Received Date & time Amount Apr",
    "Date Transaction Details Type Amount",
    "Particulars Withdrawal Deposit Balance",
])
def test_header_lines_are_recognised(line):
    assert _looks_like_header(line)


@pytest.mark.parametrize("line", ["Swiggy", "SAIKAMMILI", "Amazon Pay, India", "TATAPLAYLIMITED"])
def test_real_merchants_are_not_treated_as_headers(line):
    assert not _looks_like_header(line)


def test_header_row_is_dropped_from_csv():
    csv = (
        b"date,time,description,debit,credit,status\n"
        b"01/06/2026,09:12,Swiggy,420,,SUCCESS\n"
        b"Date,Time,Particulars,Debit,Credit,Status\n"
        b"02/06/2026,10:15,Zomato,310,,SUCCESS\n"
    )
    txs = _parse_csv_statement(csv)
    assert len(txs) == 2
    assert all(not _looks_like_header(t["merchant"]) for t in txs)


# ── Date-only statements must not all count as night transactions ─────────

def test_date_only_rows_are_excluded_from_hour_stats():
    rows = [
        {"timestamp": f"2026-06-0{d}T00:00:00", "amount": 100.0, "merchant": "M",
         "upi_id": "", "status": "SUCCESS", "reference_number": str(d), "txn_type": "DEBIT"}
        for d in range(1, 6)
    ]
    profile = generate_behavior_profile(rows)
    assert profile["night_transactions"] == 0, "a date with no time is not a night transaction"
    assert profile["most_active_hour"] is None
    assert profile["transactions_without_time"] == 5


# ── C4: re-uploading a statement must not duplicate history ───────────────

def test_reuploading_the_same_statement_inserts_nothing(tmp_path, monkeypatch):
    from backend.app.services import profile_store

    monkeypatch.setattr(profile_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(profile_store, "DB_PATH", tmp_path / "test.db")

    tx = [{"timestamp": "2026-07-01T10:00:00", "amount": 111.0, "merchant": "Shop",
           "upi_id": "", "status": "SUCCESS", "reference_number": "REF1",
           "raw_line": "x", "txn_type": "DEBIT"}]

    assert profile_store.save_statement_transactions("u1", "s1", "csv", tx) == 1
    assert profile_store.save_statement_transactions("u1", "s2", "csv", tx) == 0
    assert len(profile_store.get_user_transactions("u1")) == 1


def test_user_id_is_indexed(tmp_path, monkeypatch):
    from backend.app.services import profile_store

    monkeypatch.setattr(profile_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(profile_store, "DB_PATH", tmp_path / "test.db")
    conn = profile_store._get_connection()
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='statement_transactions'"
    )}
    conn.close()
    assert "ix_stmt_user" in names, "profile lookups were full table scans"
