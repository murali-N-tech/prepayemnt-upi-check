"""What the API accepts, and what it says when it refuses.

Three defects found by a boundary audit, each demonstrated before it was
fixed:

    a one-megabyte `payload` was checked, echoed back in full, and - through
    /payee/confirm - would have become the primary key of a reputation row

    "abc\\x00def@ybl" was accepted as an address; a NUL is where a C string
    ends, so two different payees can become one in a log, a filename or the
    next service along

    the retained copy of an uploaded statement was named with the filename from
    the multipart header, unmodified: "../../../x.csv" is a path, not a name

These tests are about the boundary only. Nothing here asserts anything about
scores, bands or evidence - the audit did not touch them, and a test that
pinned them from this file would be the wrong place to notice a change.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from backend.main import (
    MAX_CHAT_CHARS,
    MAX_CHAT_TURNS,
    MAX_MESSAGE_CHARS,
    MAX_PAYLOAD_CHARS,
    MAX_REASON_CHARS,
    MAX_VPA_CHARS,
    _safe_filename,
)

STATEMENT = (b"Date,Narration,Debit,Credit\n"
             b"01/08/2026,UPI-SHOP-shop@ybl,200.00,\n"
             b"02/08/2026,UPI-SHOP-shop@ybl,240.00,\n")


@pytest.fixture()
def api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app.services import profile_store

    monkeypatch.setattr(profile_store, "DB_PATH", tmp_path / "boundary.db")
    profile_store._SCHEMA_DONE.clear()
    import backend.main as main

    client = TestClient(main.app)
    registered = client.post("/auth/register",
                             json={"username": "alice@okaxis", "password": "hunter2hunter2"})
    assert registered.status_code == 200, registered.text
    client.headers.update({"Authorization": f"Bearer {registered.json()['token']}"})
    try:
        yield client
    finally:
        profile_store._SCHEMA_DONE.clear()


# ── Oversized text ───────────────────────────────────────────────────────────

def test_an_oversized_payload_is_refused_not_echoed(api):
    """FastAPI's default 422 body repeats the offending value, so declining a
    megabyte meant sending the megabyte back."""
    r = api.post("/payee/check", json={"payload": "a" * (MAX_PAYLOAD_CHARS + 1), "amount": 100.0})
    assert r.status_code == 422
    assert "a" * 200 not in r.text, "a refusal must not echo the thing it refused"
    assert len(r.text) < 1_000
    assert r.json()["detail"][0]["msg"], "it still says what was wrong"
    assert "input" not in r.json()["detail"][0]


def test_an_address_the_length_of_a_real_one_is_accepted(api):
    r = api.post("/payee/check", json={"payload": "srilakshmi.canteen@ybl", "amount": 90.0})
    assert r.status_code == 200, r.text


def test_a_full_upi_qr_is_comfortably_under_the_limit(api):
    qr = ("upi://pay?pa=srilakshmi.canteen@ybl&pn=SRI%20LAKSHMI%20CANTEEN&am=90.00"
          "&cu=INR&tn=" + "lunch%20" * 40)
    assert len(qr) < MAX_PAYLOAD_CHARS
    assert api.post("/payee/check", json={"payload": qr}).status_code == 200


@pytest.mark.parametrize("field,limit", [("intent", 64), ("message", MAX_MESSAGE_CHARS)])
def test_oversized_free_text_is_refused(api, field, limit):
    body = {"payload": "shop@ybl", "amount": 100.0, field: "x" * (limit + 1)}
    assert api.post("/payee/check", json=body).status_code == 422


def test_an_ordinary_message_still_gets_through(api):
    r = api.post("/payee/check", json={
        "payload": "shop@ybl", "amount": 100.0, "intent": "shop",
        "message": "Hi, please pay the balance today, the offer closes at 6pm.",
    })
    assert r.status_code == 200, r.text
    assert r.json()["verdict"] in {"APPROVE", "WARN", "STEP_UP", "BLOCK"}


def test_an_oversized_report_reason_is_refused(api):
    r = api.post("/payee/report", json={"vpa": "scam@ybl", "reason": "r" * (MAX_REASON_CHARS + 1)})
    assert r.status_code == 422
    assert api.post("/payee/report", json={"vpa": "scam@ybl",
                                           "reason": "asked me to pay a fee first"}).status_code == 200


def test_an_oversized_reported_address_is_refused(api):
    assert api.post("/payee/report",
                    json={"vpa": "v" * (MAX_VPA_CHARS + 1) + "@ybl"}).status_code == 422


def test_the_assistant_cannot_be_handed_an_unbounded_conversation(api):
    """Every turn is forwarded to the provider, so the size of this is someone
    else's bill as well as this server's memory."""
    long_history = [{"role": "user", "content": "q"}] * (MAX_CHAT_TURNS + 1)
    assert api.post("/chat", json={"message": "why?", "history": long_history}).status_code == 422
    assert api.post("/chat", json={"message": "z" * (MAX_CHAT_CHARS + 1)}).status_code == 422
    assert api.post("/chat", json={
        "message": "why did this come back as a warning?",
        "history": [{"role": "user", "content": "is this payee safe?"}],
    }).status_code == 200


# ── Control characters ───────────────────────────────────────────────────────

def test_a_nul_in_an_address_is_refused(api):
    r = api.post("/payee/check", json={"payload": "abc\x00def@ybl", "amount": 100.0})
    assert r.status_code == 422
    assert "\\u0000" not in r.text, "and the refusal does not repeat the NUL back"
    assert "control characters" in r.json()["detail"][0]["msg"]


def test_a_nul_cannot_be_reported_or_confirmed_into_the_store(api):
    assert api.post("/payee/report", json={"vpa": "abc\x00def@ybl"}).status_code == 422
    assert api.post("/payee/confirm",
                    json={"payload": "abc\x00def@ybl", "amount": 100.0}).status_code == 422


def test_ordinary_punctuation_and_unicode_are_not_control_characters(api):
    """The rule is about C0 controls, not about anything unfamiliar. A payee
    name in Telugu, or a newline in a pasted message, is not an attack."""
    r = api.post("/payee/check", json={
        "payload": "upi://pay?pa=shop@ybl&pn=%E0%B0%B6%E0%B1%8D%E0%B0%B0%E0%B1%80",
        "amount": 100.0, "message": "line one\nline two\ttabbed",
    })
    assert r.status_code == 200, r.text


# ── The retained upload ──────────────────────────────────────────────────────

@pytest.mark.parametrize("given,expected", [
    ("../../../pwned.csv", "pwned.csv"),
    ("x/../../y.csv", "y.csv"),
    ("..\\..\\win.csv", "win.csv"),
    ("C:\\Windows\\evil.pdf", "evil.pdf"),
    ("/etc/passwd", "passwd"),
    ("", "statement"),
    (None, "statement"),
    ("." * 30, "statement"),
    ("statement Jun-Sep 2026.pdf", "statement_Jun-Sep_2026.pdf"),
])
def test_a_client_filename_is_reduced_to_a_name(given, expected):
    result = _safe_filename(given)
    assert result == expected
    assert "/" not in result and "\\" not in result
    assert not result.startswith(".")
    assert len(result) <= 120


def test_a_traversing_filename_writes_inside_the_uploads_folder(api, tmp_path):
    """The whole point: the bytes land where they are supposed to, under a name
    that is a name."""
    workdir = Path(tempfile.mkdtemp())
    here = os.getcwd()
    os.chdir(workdir)
    try:
        r = api.post("/statement/upload",
                     files={"file": ("../../../pwned_statement.csv", STATEMENT, "text/csv")},
                     data={"retain_source": "true"})
        assert r.status_code == 200, r.text
        uploads = workdir / "data" / "uploaded_statements"
        written = list(uploads.glob("*"))
        assert len(written) == 1, written
        assert written[0].name.endswith("pwned_statement.csv")
        assert ".." not in written[0].name
        assert not list(workdir.glob("pwned*")), "nothing escaped the uploads folder"
        assert not list(workdir.parent.glob("pwned*"))
    finally:
        os.chdir(here)


# ── Error responses ──────────────────────────────────────────────────────────

def test_an_unreadable_upload_is_a_bad_request_not_a_server_error(api):
    r = api.post("/statement/upload",
                 files={"file": ("broken.pdf", b"%PDF-1.4 truncated", "application/pdf")})
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "could not be read" in detail
    for leak in ("Traceback", "Stream has ended", "pdfplumber", "pypdf", "/", "\\"):
        assert leak not in detail, f"the error names an internal detail: {leak!r}"


def test_a_validation_failure_keeps_its_shape_and_status(api):
    """The contract the frontend reads: 422, `detail` a list, each entry with
    loc / msg / type. Only the echoed value is gone."""
    r = api.post("/payee/check", json={"amount": 100.0})     # payload missing
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, list) and detail
    for entry in detail:
        assert set(entry) == {"loc", "msg", "type"}
        assert isinstance(entry["loc"], list)


def test_an_empty_upload_is_still_refused_the_same_way(api):
    r = api.post("/statement/upload", files={"file": ("empty.pdf", b"", "application/pdf")})
    assert r.status_code == 400
    assert isinstance(r.json()["detail"], str)


def test_a_readable_statement_still_uploads(api):
    r = api.post("/statement/upload", files={"file": ("statement.csv", STATEMENT, "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["transactions_extracted"] >= 1


# ── Unchanged: what this audit must not have touched ─────────────────────────

def test_the_response_contract_is_unchanged_for_a_normal_check(api):
    r = api.post("/payee/check", json={"payload": "srilakshmi.canteen@ybl", "amount": 90.0,
                                       "intent": "shop"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"risk_score", "confidence_score", "evidence_level", "verdict",
            "evidence", "missing_evidence"} <= set(body)
    assert body["verdict"] == body["decision"]
    for row in body["evidence"]:
        if not row["available"]:
            assert row["score"] is None, "unavailable evidence still carries no score"


def test_every_user_scoped_endpoint_still_requires_a_token(api):
    from fastapi.testclient import TestClient
    import backend.main as main

    anonymous = TestClient(main.app)
    for path in ("/heatmap", "/fraud-graph", "/fraud-rings", "/temporal-patterns",
                 "/model-drift", "/gnn-fraud-detection", "/profiles/me",
                 "/statement-transactions", "/transactions"):
        assert anonymous.get(path).status_code == 401, path
    assert anonymous.post("/payee/check", json={"payload": "shop@ybl"}).status_code == 401
    assert anonymous.post("/chat", json={"message": "hello"}).status_code == 401
