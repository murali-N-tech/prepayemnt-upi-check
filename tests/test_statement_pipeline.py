

# ── Time in real app statements ───────────────────────────────────────────
#
# Both of these come from statements that DO print the time on every row. The
# PhonePe font has no ToUnicode entry for the colon, so pdfplumber returns a
# control character in its place, and the time was lost twice over: unmatched
# by the time regex, and left glued onto the merchant name.

import pytest  # noqa: E402

from backend.app.services.statement_parser import (  # noqa: E402
    _BLOCK_TIME_RE,
    _normalize_text,
    _parse_clock,
    _repair_lost_glyphs,
)


def test_a_colon_lost_by_the_font_is_restored():
    assert _repair_lost_glyphs("10\x0016 pm") == "10:16 pm"
    assert _repair_lost_glyphs("04\x0057 pm Transaction ID T26") == "04:57 pm Transaction ID T26"


def test_control_characters_elsewhere_become_spaces_not_colons():
    """Only a control character BETWEEN DIGITS is a lost colon."""
    assert ":" not in _repair_lost_glyphs("Paid to\x00Srinivas shop")


def test_lowercase_pm_is_matched():
    """PhonePe writes 'pm', Google Pay writes 'AM'. Both are times."""
    assert _BLOCK_TIME_RE.search("10:16 pm Transaction ID")
    assert _BLOCK_TIME_RE.search("10:50AM UPITransactionID")


@pytest.mark.parametrize("raw,expected", [
    ("10\x0016 pm", "10:16 pm"),      # PhonePe: colon lost to the font
    ("09\x0055 am", "09:55 am"),
    ("10:50AM", "10:50AM"),           # Google Pay: intact, no space
])
def test_app_statement_times_survive_normalisation(raw, expected):
    fixed = _normalize_text(raw)
    assert fixed == expected
    assert _parse_clock(_BLOCK_TIME_RE.search(fixed).group(0)) is not None


def test_two_identical_payments_on_one_day_are_both_kept():
    """A tea shop twice in a day is ordinary, not a duplicate.

    The block de-duplicator keyed on (date, description, amount) with no time
    and no transaction reference. It only appeared to work because the
    unparsed time was still sitting in the description making the two rows
    look different.
    """
    from backend.app.services.statement_parser import _Transaction

    def row(time_str, ref):
        return _Transaction(
            date="2026-08-17", time_str=time_str, description="Srinivas cold drink shop",
            debit=20.0, credit=None, balance=None, is_upi=True, upi_ref=ref,
            vpa=None, txn_type="DEBIT", source_file="s.pdf", raw_line="",
        )

    a, b = row("04:57 pm", "T2608171657"), row("11:19 pm", "T2608172319")
    key = lambda t: (t.date, t.time_str, t.description, t.debit, t.credit, t.balance, t.upi_ref)
    assert key(a) != key(b)
