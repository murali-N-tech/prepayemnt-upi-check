"""The dashboard said "most active hour: 12:00" for statements that never
carried a clock time at all.

The PDF path wrote 12:00:00 for every transaction, and nothing downstream
could tell that placeholder apart from a real midday payment. These tests
pin the behaviour that replaced it: a row whose time was never in the
statement is recorded as time-unknown and left out of hour statistics.
"""

from __future__ import annotations

import pytest

from backend.app.services.statement_parser import generate_behavior_profile


def _rows(times, *, flag=True):
    """One transaction per entry; `times` may hold None for 'no clock time'."""
    out = []
    for i, clock in enumerate(times):
        day = f"2026-03-{(i % 27) + 1:02d}"
        out.append(
            {
                "timestamp": f"{day}T{clock or '00:00:00'}",
                "amount": 100.0 + i,
                "merchant": f"shop {i}",
                "upi_id": f"shop{i}@okaxis",
                "status": "SUCCESS",
                "txn_type": "DEBIT",
                **({"time_known": clock is not None} if flag else {}),
            }
        )
    return out


def test_statement_with_no_times_reports_no_active_hour():
    profile = generate_behavior_profile(_rows([None] * 12))
    assert profile["most_active_hour"] is None, \
        "a statement with no clock times claimed to know when the user pays"
    assert profile["transactions_without_time"] == 12
    assert profile["hourly_distribution"] == {}


def test_untimed_rows_are_not_counted_as_night_transactions():
    profile = generate_behavior_profile(_rows([None] * 10))
    assert profile["night_transactions"] == 0, \
        "midnight placeholders were counted as 10 night payments"


def test_real_times_survive_alongside_untimed_rows():
    profile = generate_behavior_profile(_rows([None, None, "19:30:00", "19:45:00", "19:10:00"]))
    assert profile["most_active_hour"] == 19
    assert profile["transactions_without_time"] == 2
    assert {int(h) for h in profile["hourly_distribution"]} == {19}


def test_dates_still_count_when_the_time_is_unknown():
    # The date is known even when the clock is not, so day-level statistics
    # must not silently drop those rows.
    profile = generate_behavior_profile(_rows([None] * 8))
    assert profile["transaction_count"] == 8
    assert profile["average_daily_transactions"] > 0


@pytest.mark.parametrize("sentinel", ["00:00:00", "12:00:00"])
def test_legacy_rows_without_the_flag_treat_both_sentinels_as_unknown(sentinel):
    # Rows written before time_known existed. Noon is the one the PDF path
    # used, and it is the reason the dashboard said 12:00.
    profile = generate_behavior_profile(_rows([sentinel] * 9, flag=False))
    assert profile["most_active_hour"] is None
    assert profile["transactions_without_time"] == 9


def test_a_genuine_noon_payment_is_kept_when_the_flag_says_so():
    # 12:00:00 with time_known=True came from a statement that really said
    # noon, and must not be discarded along with the placeholders.
    rows = _rows(["12:00:00"] * 3 + ["12:15:00"] * 2)
    profile = generate_behavior_profile(rows)
    assert profile["most_active_hour"] == 12
    assert profile["transactions_without_time"] == 0
