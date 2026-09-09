"""The findings that were still open after the first fix pass.

H7 behaviour_score mixed scales, M2 merchant names were compared raw,
H6 transactions were a rewritten CSV, C9 two user stores.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.app.services import profile_store
from backend.app.services.behavioral_biometrics import behaviour_risk, behavior_score
from backend.app.services.merchant import (
    is_masked_account,
    merchant_key,
    normalise_merchant,
)
from backend.app.services.personalized_risk_service import evaluate_personalized_risk
from backend.app.services.statement_parser import generate_behavior_profile


# ── H7: a count and a 0-1 score were averaged together ────────────────────

def test_ordinary_activity_is_not_high_risk():
    """np.mean([2, 0.5]) is 1.25, which cleared the old 0.8 threshold. Two
    payments on a normal device was reported as High Risk."""
    assert behavior_score(2, 0.5) == "Normal"
    assert behavior_score(1, 0.1) == "Normal"
    assert behavior_score(3, 0.3) == "Normal"


def test_a_real_burst_is_still_high_risk():
    assert behavior_score(14, 0.9) == "High Risk"
    assert behavior_score(15, 1.0) == "High Risk"


def test_the_score_is_bounded_and_monotonic():
    assert 0.0 <= behaviour_risk(0, 0.0) <= 1.0
    assert behaviour_risk(15, 1.0) == pytest.approx(1.0)
    assert behaviour_risk(2, 0.5) < behaviour_risk(8, 0.5) < behaviour_risk(14, 0.5)


def test_velocity_beyond_the_cap_does_not_overflow():
    assert behaviour_risk(500, 1.0) <= 1.0


@pytest.mark.parametrize("bad", [None, "", "abc"])
def test_garbage_inputs_do_not_raise(bad):
    assert behavior_score(bad, bad) in {"Normal", "Medium Risk", "High Risk"}


# ── M2: payee identity ────────────────────────────────────────────────────

@pytest.mark.parametrize("a,b", [
    ("CHINTHADA MURALI NAGARAJU", "Chinthada Murali Nagaraju"),
    ("Amazon Pay", "AMAZON  PAY"),
    ("Sri Balaji Traders Pvt Ltd", "SRI BALAJI TRADERS PRIVATE LIMITED"),
    ("Big-Basket", "BigBasket"),
])
def test_the_same_payee_written_differently_matches(a, b):
    assert merchant_key(a) == merchant_key(b) != ""


def test_different_payees_do_not_collide():
    assert merchant_key("Swiggy") != merchant_key("Zomato")


def test_a_masked_account_number_is_not_an_identity():
    """Treating every 'XX1468' as one payee would merge unrelated people."""
    assert is_masked_account("XX1468")
    assert merchant_key("XX1468") == ""


def test_the_vpa_wins_over_the_display_name():
    assert merchant_key("Swiggy India", "swiggy@ibl") == "swiggy@ibl"
    assert merchant_key("Anything At All", "SWIGGY@IBL") == "swiggy@ibl"


def test_noise_words_alone_do_not_make_a_key():
    assert normalise_merchant("Pvt Ltd") == ""


def _profile_with(merchants):
    txs = [
        {"timestamp": f"2026-06-0{i}T10:00:00", "amount": 400.0, "merchant": m,
         "upi_id": "", "status": "SUCCESS", "reference_number": str(i), "txn_type": "DEBIT"}
        for i, m in enumerate(merchants, start=1)
    ]
    return generate_behavior_profile(txs), pd.DataFrame(txs)


def test_a_repeat_payee_no_longer_trips_the_new_merchant_rule():
    profile, history = _profile_with(["CHINTHADA MURALI NAGARAJU", "Swiggy"])
    result = evaluate_personalized_risk(
        profile=profile, history=history, amount=400,
        merchant="chinthada murali nagaraju", timestamp="2026-06-05T10:00:00",
    )
    assert not any("not appeared" in r for r in result["reasons"])


def test_a_genuinely_new_payee_still_does():
    profile, history = _profile_with(["Swiggy", "Zomato"])
    result = evaluate_personalized_risk(
        profile=profile, history=history, amount=400,
        merchant="Unknown Trader", timestamp="2026-06-05T10:00:00",
    )
    assert any("not appeared" in r for r in result["reasons"])


def test_a_known_upi_id_matches_regardless_of_case():
    txs = [{"timestamp": "2026-06-01T10:00:00", "amount": 400.0, "merchant": "Swiggy",
            "upi_id": "swiggy@ibl", "status": "SUCCESS", "reference_number": "1",
            "txn_type": "DEBIT"}]
    profile = generate_behavior_profile(txs)
    result = evaluate_personalized_risk(
        profile=profile, history=pd.DataFrame(txs), amount=400,
        merchant="Swiggy", timestamp="2026-06-02T10:00:00", upi_id="SWIGGY@IBL",
    )
    assert not any("UPI ID is new" in r for r in result["reasons"])


def test_the_profile_carries_the_keys():
    profile, _ = _profile_with(["Swiggy", "XX1468"])
    assert "name:swiggy" in profile["known_merchant_keys"]
    assert "" not in profile["known_merchant_keys"]


# ── H6: scored transactions ───────────────────────────────────────────────

@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(profile_store, "DB_PATH", tmp_path / "tx.db")
    from backend.app.services import transaction_store as ts
    conn = ts.connect()
    yield ts, conn
    conn.close()


def _tx(tid, sender="u1", amount=100.0):
    return {"transaction_id": tid, "amount": amount, "device_score": 0.1,
            "location_score": 0.1, "velocity_score": 1, "sender": sender,
            "receiver": "m1", "timestamp": "2026-09-09T10:00:00", "risk": 0,
            "risk_score": 5}


def test_saving_is_an_append_not_a_rewrite(store):
    ts, conn = store
    for i in range(20):
        ts.save_transaction(_tx(f"tx_{i}"), conn=conn)
    assert len(ts.get_all_transactions(conn=conn)) == 20


def test_transactions_can_be_scoped_to_one_payer(store):
    ts, conn = store
    ts.save_transaction(_tx("tx_a", sender="alice"), conn=conn)
    ts.save_transaction(_tx("tx_b", sender="bob"), conn=conn)
    assert len(ts.get_all_transactions(sender="alice", conn=conn)) == 1


def test_ordering_puts_the_newest_last_so_tail_means_latest(store):
    ts, conn = store
    for i in range(5):
        ts.save_transaction(_tx(f"tx_{i}", amount=float(i)), conn=conn)
    assert ts.get_all_transactions(conn=conn).tail(1)["transaction_id"].iloc[0] == "tx_4"


def test_a_repeated_id_does_not_duplicate_the_row(store):
    ts, conn = store
    ts.save_transaction(_tx("tx_same"), conn=conn)
    ts.save_transaction(_tx("tx_same", amount=999.0), conn=conn)
    df = ts.get_all_transactions(conn=conn)
    assert len(df) == 1 and df.iloc[0]["amount"] == 999.0


def test_lookup_by_id(store):
    ts, conn = store
    ts.save_transaction(_tx("tx_find"), conn=conn)
    assert ts.get_transaction("tx_find", conn=conn)["transaction_id"] == "tx_find"
    assert ts.get_transaction("nope", conn=conn) is None


def test_sender_is_indexed(store):
    _, conn = store
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='scored_transactions'")}
    assert "ix_scored_sender" in names


# ── temporal patterns over mixed timestamp formats ────────────────────────

def test_hour_histogram_survives_mixed_timestamp_formats():
    """Migrated rows carry several formats, some with a timezone and some
    without. pandas infers one format and then raises on the first that
    differs, which took the endpoint down."""
    from backend.app.services.temporal_gnn import temporal_patterns

    df = pd.DataFrame([
        {"timestamp": "2026-07-19T02:43:00", "risk": 1},
        {"timestamp": "2026-07-19 12:00:00.123456", "risk": 1},
        {"timestamp": "2026-07-19T18:30:00+00:00", "risk": 0},
        {"timestamp": "not a date", "risk": 1},
    ])
    result = temporal_patterns(df)
    assert len(result) == 24
    assert result["2"] == 1 and result["12"] == 1 and result["18"] == 0
