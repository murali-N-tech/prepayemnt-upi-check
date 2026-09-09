"""Accounts are identified by the UPI ID they pay from.

The rule these tests exist to defend: nothing anywhere reports a UPI ID as
verified unless a verification provider actually confirmed it. Format checks
and a known PSP handle are not the same claim as "this account exists".
"""

from __future__ import annotations

import pytest

from backend.app.services import upi_verify
from backend.app.services.upi_verify import verify_vpa


# ── UPI ID verification ───────────────────────────────────────────────────

def test_malformed_upi_id_is_rejected():
    result = verify_vpa("not-a-upi-id")
    assert result.status == "malformed"
    assert not result.ok


def test_unknown_bank_handle_is_rejected():
    result = verify_vpa("murali@okaxls")   # okaxis with a lowercase L
    assert result.status == "malformed"
    assert "handle" in result.detail.lower()


def test_wellformed_id_is_unavailable_not_verified_without_a_provider(monkeypatch):
    monkeypatch.setattr(upi_verify, "get", lambda name, default: "" if name == "UPI_VERIFY_URL" else default)
    result = verify_vpa("Murali@OKAXIS")
    assert result.status == "unavailable"
    assert result.vpa == "murali@okaxis", "the address should be normalised to lower case"
    assert not result.ok, "an unchecked address must never read as verified"
    assert not result.checked_with_provider
    assert result.as_dict()["verified_by_provider"] is False


def test_provider_confirmation_is_the_only_route_to_verified(monkeypatch):
    monkeypatch.setattr(
        upi_verify, "get",
        lambda name, default: {
            "UPI_VERIFY_URL": "https://psp.example/validate",
            "UPI_VERIFY_PROVIDER": "test-psp",
        }.get(name, default),
    )
    monkeypatch.setattr(
        upi_verify, "_call_provider",
        lambda url, key, vpa: {"valid": True, "name": "MURALI N"},
    )
    result = verify_vpa("murali@okaxis")
    assert result.status == "verified"
    assert result.ok and result.checked_with_provider
    assert result.name == "MURALI N"


def test_provider_outage_does_not_read_as_a_fake_address(monkeypatch):
    def boom(url, key, vpa):
        raise TimeoutError("provider down")

    monkeypatch.setattr(
        upi_verify, "get",
        lambda name, default: "https://psp.example/validate" if name == "UPI_VERIFY_URL" else default,
    )
    monkeypatch.setattr(upi_verify, "_call_provider", boom)
    result = verify_vpa("murali@okaxis")
    assert result.status == "unavailable", "an outage must not be reported as not_found"
    assert not result.ok


# ── Registration is by UPI ID ─────────────────────────────────────────────

@pytest.fixture()
def api(tmp_path, monkeypatch):
    """A TestClient over a throwaway database."""
    from fastapi.testclient import TestClient
    from backend.app.services import profile_store

    monkeypatch.setattr(profile_store, "DB_PATH", tmp_path / "auth.db")
    import backend.main as main
    return TestClient(main.app)


def test_registering_with_a_username_is_refused(api):
    response = api.post("/auth/register", json={"username": "murali", "password": "hunter2hunter2"})
    assert response.status_code == 400
    assert "upi id" in response.json()["detail"].lower()


def test_registering_with_a_bad_handle_is_refused(api):
    response = api.post(
        "/auth/register", json={"username": "murali@okaxls", "password": "hunter2hunter2"}
    )
    assert response.status_code == 400


def test_registering_with_a_upi_id_works_and_claims_nothing_extra(api):
    response = api.post(
        "/auth/register", json={"username": "Murali@OKAXIS", "password": "hunter2hunter2"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["upi_id"] == "murali@okaxis", "the UPI ID should be stored lower case"
    assert body["upi_verified"] is False, \
        "no provider is configured in tests, so nothing may claim verification"
    assert body["token"]


def test_the_same_upi_id_cannot_register_twice(api):
    payload = {"username": "murali@okaxis", "password": "hunter2hunter2"}
    assert api.post("/auth/register", json=payload).status_code == 200
    assert api.post("/auth/register", json=payload).status_code == 400


def test_login_accepts_the_upi_id_in_any_case(api):
    api.post("/auth/register", json={"username": "murali@okaxis", "password": "hunter2hunter2"})
    response = api.post(
        "/auth/login", json={"username": "MURALI@OKAXIS", "password": "hunter2hunter2"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["upi_id"] == "murali@okaxis"


def test_login_does_not_reveal_whether_a_upi_id_is_registered(api):
    api.post("/auth/register", json={"username": "murali@okaxis", "password": "hunter2hunter2"})
    wrong_password = api.post(
        "/auth/login", json={"username": "murali@okaxis", "password": "wrongwrongwrong"}
    )
    no_such_user = api.post(
        "/auth/login", json={"username": "nobody@okaxis", "password": "wrongwrongwrong"}
    )
    assert wrong_password.status_code == no_such_user.status_code == 401
    assert wrong_password.json()["detail"] == no_such_user.json()["detail"]


def test_upi_status_does_not_advertise_a_check_it_cannot_do(api):
    body = api.get("/auth/upi-status").json()
    assert body["provider_configured"] is False
    assert "account exists" not in body["checks"]
