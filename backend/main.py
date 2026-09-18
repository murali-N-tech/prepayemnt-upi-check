import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi import File, Form, UploadFile
from pydantic import BaseModel, field_validator
import uuid
import numpy as np
import pandas as pd
import shap
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from fastapi.security import OAuth2PasswordBearer
from fastapi import Depends


# SERVICES
from backend.app.services.transaction_store import (
    save_transaction,
    get_all_transactions,
    get_transaction
)
from backend.app.services.profile_store import (
    get_behavior_profile,
    get_user_transactions,
    save_behavior_profile,
    save_statement_transactions,
    get_all_edges,
)
from backend.app.services.statement_parser import (
    generate_behavior_profile,
    parse_statement_file,
)
from backend.app.services.personalized_risk_service import (
    evaluate_personalized_risk,
)
from backend.app.services.fraud_graph import detect_rings, graph_summary, load_edges
from backend.app.services.chat import answer as chat_answer, is_configured as chat_configured
from backend.app.services.intent import INTENTS
from backend.app.services.payee_check import check_payee
from backend.app.services.upi_verify import (
    is_configured as upi_verifier_configured,
    verification_required as upi_verification_required,
    verify_vpa,
)
from backend.app.services.payee_reputation import payer_has_paid, record_payment, report_payee

from backend.app.services.behavioral_biometrics import (
    behavior_score,
    behaviour_risk,
    normalised_velocity,
)
from backend.app.services.temporal_gnn import temporal_patterns
from backend.app.services.drift_monitor import detect_drift, drift_report

from backend.app.core.security import hash_password, verify_password, create_token, verify_token
from backend.app.core.upi_limits import check_amount, describe_cap, standard_cap
from backend.app.core.json_safe import json_safe
from backend.app.core.verdict import verdict_from_score
from backend.app.services.profile_store import create_user, get_user_by_username


# GRAPH
from backend.graph.graph_fraud_detector import (
    add_connection,
    get_graph,
    detect_fraud_rings
)

# MODEL
from backend.models.ensemble_model import load_metrics, load_model
from backend.ml.dataset import FEATURES as MODEL_FEATURES
from backend.ml.features import build_features, to_frame
from backend.app.services.payee_reputation import assess_payee, payee_key

# GNN
from backend.advanced_ai.gnn_fraud_detector import gnn_risk


app = FastAPI()


@app.exception_handler(RequestValidationError)
def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """A refusal that does not repeat what it refused.

    FastAPI's default 422 body carries an `input` field holding the offending
    value, so the endpoint that declines a one-megabyte payload answered by
    sending the megabyte back - and the endpoint that rejects a NUL in an
    address wrote that NUL into its own response. The status code, the
    `detail` list and its loc/msg/type entries are exactly as before; only the
    echo and the internal `ctx` object are dropped.
    """
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {"loc": [str(part) for part in error.get("loc", [])],
                 "msg": str(error.get("msg", ""))[:300],
                 "type": str(error.get("type", ""))}
                for error in exc.errors()
            ]
        },
    )


# --------------------------------------------------
# Load ML Model
# --------------------------------------------------

MODEL_METRICS = load_metrics()

# The decision threshold is not a round number someone liked. It is the point
# the training run chose to satisfy a stated false-positive budget, and it is
# reported in models/metrics.json alongside the recall it buys.
DECISION_THRESHOLD = float(
    MODEL_METRICS.get("selected", {}).get("operating_point", {}).get("threshold", 0.5)
)
FPR_BUDGET = float(
    MODEL_METRICS.get("selected", {}).get("operating_point", {}).get("fpr_budget", 0.01)
)

_BACKGROUND_PATH = Path("models") / "shap_background.json"

# The model is loaded on first use rather than at import. A pickle is tied to
# the library versions that produced it, so an untrained or mismatched model is
# a normal thing to hit on a new machine - and it should not take down the
# payee check, the statement parsing or anything else that does not need it.
_model = None
_explainer = None


def get_model():
    global _model
    if _model is None:
        _model = load_model()
    return _model


def get_explainer():
    """SHAP explains against a sample of real training traffic. Explaining
    against noise, which an earlier version did, is not explanation."""
    global _explainer
    if _explainer is None:
        if not _BACKGROUND_PATH.exists():
            raise RuntimeError(
                f"No SHAP background at {_BACKGROUND_PATH}.\n\n"
                "    Train the model:  python backend/train_model.py"
            )
        background = pd.read_json(_BACKGROUND_PATH, orient="split")[MODEL_FEATURES]

        def shap_predict(X):
            frame = pd.DataFrame(X, columns=MODEL_FEATURES)
            return get_model().predict_proba(frame)[:, 1]

        _explainer = shap.Explainer(shap_predict, background.to_numpy())
    return _explainer


def model_or_503():
    """Turn a missing or unloadable model into an answer the caller can act
    on, rather than a 500 and a pickle traceback in the log."""
    try:
        return get_model()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# --------------------------------------------------
# Transaction Schema
# --------------------------------------------------

class Transaction(BaseModel):

    amount: float
    device_score: float
    location_score: float
    velocity_score: float
    sender: str
    receiver: str
    timestamp: str

    @field_validator("amount")
    @classmethod
    def _amount_is_a_possible_upi_payment(cls, value: float) -> float:
        """A bare `amount: float` accepted anything. Measured before this:
        -5000 scored risk=0 and came back "APPROVED", and 1e12 - one lakh
        crore - was scored as a real payment. Neither can move over UPI, so a
        fraud verdict on either is a verdict about a payment that cannot
        happen. 422 is the honest answer.

        The standard cap applies here: /predict takes a bare amount with no QR,
        so nothing has established the payee is a verified merchant.
        """
        problem = check_amount(value)
        if problem:
            raise ValueError(problem)
        return float(value)


class PersonalizedRiskCheck(BaseModel):

    amount: float
    merchant: str
    timestamp: str
    upi_id: str | None = None
    location: str | None = None

    @field_validator("amount")
    @classmethod
    def _amount_is_a_possible_upi_payment(cls, value: float) -> float:
        problem = check_amount(value)
        if problem:
            raise ValueError(problem)
        return float(value)

class UserAuth(BaseModel):
    username: str
    password: str


# What the API accepts as text, and why there is a limit at all.
#
# These fields were unbounded strings. A one-megabyte `payload` was checked in
# 80ms and echoed back in full, and the same string sent to /payee/confirm
# becomes the primary key of a reputation row - a megabyte of it, keyed
# forever. Nothing legitimate is anywhere near these sizes:
#
#   a UPI QR is a single upi://pay?... URI, a few hundred bytes
#   a VPA is an address, not a document
#   an intent is one of six ids, the longest being "investment"
#
# Generous enough that no real input is refused, small enough that no caller
# can turn one request into a stored megabyte or a 150KB response.
MAX_PAYLOAD_CHARS = 4_096
MAX_VPA_CHARS = 255
MAX_INTENT_CHARS = 64
MAX_MESSAGE_CHARS = 2_000
MAX_REASON_CHARS = 500
MAX_CHAT_CHARS = 4_000
MAX_CHAT_TURNS = 20


def _clean_text(value: str | None, field: str, limit: int) -> str | None:
    """Reject what cannot be a real address, message or reason.

    NUL in particular: it was accepted as part of a VPA, echoed into the
    response and would have gone into the store as part of a key. A C string
    somewhere downstream - a log file, a filename, another service - reads that
    as the end of the address, so two different payees can become one.
    """
    if value is None:
        return None
    if len(value) > limit:
        raise ValueError(f"{field} is too long (limit {limit} characters).")
    if any(ord(ch) < 32 and ch not in "\t\r\n" for ch in value):
        raise ValueError(f"{field} contains control characters.")
    return value


class PayeeCheckRequest(BaseModel):
    """`payload` is a scanned QR, a pasted UPI ID, or a phone number."""
    payload: str
    amount: float | None = None

    @field_validator("amount")
    @classmethod
    def _amount_is_not_absurd(cls, value: float | None) -> float | None:
        """Sign and finiteness only. WHICH cap applies depends on the QR - a
        signed merchant QR may carry up to Rs 5 lakh - so the cap itself is
        checked inside check_payee(), where the merchant code is known, and it
        becomes a FINDING there rather than a 422: a QR demanding more than UPI
        allows is evidence about that QR, not a bad request from the user."""
        if value is None:
            return None
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise ValueError("That amount is not a number.")
        if v != v or v in (float("inf"), float("-inf")):
            raise ValueError("That amount is not a number.")
        if v < 0:
            raise ValueError("An amount cannot be negative.")
        return v
    # What the payer says they are doing. One of intent.INTENTS.
    intent: str | None = None
    # The message that prompted this payment, if the payer chose to share it.
    # Opt-in, scored in memory, and never stored - see /payee/intents.
    message: str | None = None

    @field_validator("payload")
    @classmethod
    def _payload_is_a_payment_address(cls, value: str) -> str:
        return _clean_text(value, "The scanned or pasted address", MAX_PAYLOAD_CHARS)

    @field_validator("intent")
    @classmethod
    def _intent_is_short(cls, value: str | None) -> str | None:
        return _clean_text(value, "The stated purpose", MAX_INTENT_CHARS)

    @field_validator("message")
    @classmethod
    def _message_is_a_message(cls, value: str | None) -> str | None:
        return _clean_text(value, "The message", MAX_MESSAGE_CHARS)


class PayeeReportRequest(BaseModel):
    vpa: str
    reason: str | None = None

    @field_validator("vpa")
    @classmethod
    def _vpa_is_an_address(cls, value: str) -> str:
        return _clean_text(value, "The address", MAX_VPA_CHARS)

    @field_validator("reason")
    @classmethod
    def _reason_is_short(cls, value: str | None) -> str | None:
        return _clean_text(value, "The reason", MAX_REASON_CHARS)


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    """A question for the assistant.

    `check_result` is whatever /payee/check last returned on this screen, sent
    back so the assistant can explain THAT verdict. It is echoed evidence, not
    authority: nothing in it can change a decision, because the assistant has no
    way to make one. Everything about the person's own history is looked up
    here from their token, never accepted from the client.
    """
    message: str
    history: list[ChatTurn] = []
    check_result: dict | None = None

    @field_validator("message")
    @classmethod
    def _question_is_a_question(cls, value: str) -> str:
        return _clean_text(value, "The question", MAX_CHAT_CHARS)

    @field_validator("history")
    @classmethod
    def _history_is_bounded(cls, value: list[ChatTurn]) -> list[ChatTurn]:
        """A conversation, not a payload. Every turn here is forwarded to the
        assistant provider, so an unbounded history is someone else's bill."""
        if len(value) > MAX_CHAT_TURNS:
            raise ValueError(f"Conversation history is too long (limit {MAX_CHAT_TURNS} turns).")
        for turn in value:
            _clean_text(turn.content, "A conversation turn", MAX_CHAT_CHARS)
        return value

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def _payer_context(sender: str, current_time: str) -> dict[str, float]:
    """The payer-history part of the feature vector, computed once.

    /explain used to omit seconds_since_last_txn, txns_last_hour and
    txns_today entirely and fall back to the defaults, so it explained a
    vector the model was never given - on roughly one transaction in twenty
    that vector produces the opposite decision. One function now serves both
    endpoints so they cannot disagree.
    """
    NO_PRIOR_GAP = 86_400.0
    df = get_all_transactions(sender=sender, limit=200)
    now = pd.to_datetime(current_time, errors="coerce", utc=True)

    context = {
        "seconds_since_last_txn": NO_PRIOR_GAP,
        "txns_last_hour": 0.0,
        "txns_today": 1.0,
    }
    if df is None or df.empty or pd.isna(now):
        return context

    stamps = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    stamps = stamps.dropna()
    if stamps.empty:
        return context

    delta = (now - stamps.max()).total_seconds()
    # Clamp: clock skew or an out-of-order timestamp must not become a
    # negative gap, which reads as the strongest velocity signal there is.
    context["seconds_since_last_txn"] = float(min(max(delta, 1.0), NO_PRIOR_GAP))

    # A real count of this payer's payments in the past hour. The model was
    # trained on a COUNT; serving used to pass tx.velocity_score, which this
    # same file synthesises as risk_score/10 - a score, not a count.
    context["txns_last_hour"] = float(((now - stamps).dt.total_seconds() <= 3600).sum())
    context["txns_today"] = float((stamps.dt.date == now.date()).sum()) + 1.0
    return context


def get_current_user(token: str = Depends(oauth2_scheme)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user_id

# --------------------------------------------------
# Auth Endpoints
# --------------------------------------------------

@app.post("/auth/register")
def register(user: UserAuth):
    """Accounts are identified by the UPI ID they pay from.

    Using the payer's own address as the identity is what lets the rest of the
    system line their statement up with the payee graph, instead of guessing
    from a username that means nothing outside this app.
    """
    upi_id = (user.username or "").strip().lower()
    if not upi_id or not user.password:
        raise HTTPException(status_code=400, detail="UPI ID and password are required")
    if len(user.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    check = verify_vpa(upi_id)
    if check.status in {"malformed", "not_found"}:
        raise HTTPException(status_code=400, detail=check.detail)
    if check.status == "unavailable" and upi_verification_required():
        raise HTTPException(
            status_code=503,
            detail=f"{check.detail} Registration requires verification "
                   f"(UPI_VERIFY_REQUIRED is set), so please try again shortly.",
        )

    # Full uuid, as with tx ids. hex[:8] is 32 bits: a collision has a 1%
    # chance by about 9,300 accounts, and because user_id is the primary key
    # the insert would fail and report "That UPI ID is already registered" to
    # somebody whose address was not registered at all.
    user_id = f"usr_{uuid.uuid4().hex}"
    hashed = hash_password(user.password)
    success = create_user(user_id, upi_id, hashed, upi_id=upi_id, upi_verified=check.ok)
    if not success:
        raise HTTPException(status_code=400, detail="That UPI ID is already registered")

    token = create_token(user_id)
    return {
        "token": token,
        "user_id": user_id,
        "username": upi_id,
        "upi_id": upi_id,
        # Only ever true when a provider actually confirmed it.
        "upi_verified": check.ok and check.checked_with_provider,
        "verification": check.as_dict(),
    }

@app.post("/auth/login")
def login(user: UserAuth):
    identifier = (user.username or "").strip().lower()
    db_user = get_user_by_username(identifier)
    if not db_user or not verify_password(user.password, db_user["password_hash"]):
        # One message for both cases, so this cannot be used to find out which
        # UPI IDs are registered.
        raise HTTPException(status_code=401, detail="Invalid UPI ID or password")

    token = create_token(db_user["id"])
    return {
        "token": token,
        "user_id": db_user["id"],
        "username": db_user["username"],
        "upi_id": db_user["upi_id"] or db_user["username"],
        "upi_verified": bool(db_user["upi_verified"]),
    }



# --------------------------------------------------
# Root
# --------------------------------------------------

@app.get("/")
def home():
    return {"message": "Edge AI UPI Behaviour Risk System Running"}


@app.get("/auth/upi-status")
def upi_status():
    """Whether UPI IDs are being checked against the payment network.

    The UI needs to be able to say "format checked" rather than "verified"
    when no provider is configured.
    """
    return {
        "provider_configured": upi_verifier_configured(),
        "verification_required": upi_verification_required(),
        "checks": ["format", "psp handle"]
        + (["account exists"] if upi_verifier_configured() else []),
    }


@app.get("/health")
def health():
    """Reports whether the trained model is usable, so a missing or mismatched
    one shows up here rather than at the first prediction."""
    model_status = "ready"
    model_detail = None
    try:
        get_model()
    except RuntimeError as exc:
        model_status = "unavailable"
        model_detail = str(exc).splitlines()[0]

    return {
        "status": "ok",
        "model": model_status,
        "model_detail": model_detail,
        "trained_with": MODEL_METRICS.get("environment"),
    }


# --------------------------------------------------
# Fraud Prediction
# --------------------------------------------------

@app.post("/predict")
def predict(tx: Transaction, user: str = Depends(get_current_user)):
    # The payer is whoever holds the token. Express already overwrites
    # tx.sender, but the Python service is reachable directly, and a
    # client-supplied sender let anyone write scored rows under another
    # user's id - which is what /heatmap, /transactions and the behaviour
    # profile all read back.
    tx = tx.model_copy(update={"sender": user})

    try:
        current_time = pd.to_datetime(tx.timestamp)
        hour = current_time.hour
    except:
        current_time = pd.Timestamp.now()
        hour = 12

    is_night = 1 if hour < 6 or hour > 22 else 0

    # This payer's own recent activity, not everyone's. Reading the global
    # table meant "seconds since last transaction" was measured against a
    # stranger's payment, which produced 0 - or a negative number - and fed
    # the model a value it never saw in training.
    # The model is trained on these exact features (backend/ml/features.py is
    # the single mapping, so training and serving cannot drift apart).
    payer_profile = get_behavior_profile(tx.sender)
    payee = assess_payee(payee_key(tx.receiver, tx.receiver))

    context = _payer_context(tx.sender, current_time)
    features = build_features(
        amount=tx.amount,
        timestamp=tx.timestamp,
        profile=payer_profile,
        reputation=payee.as_dict(),
        seconds_since_last_txn=context["seconds_since_last_txn"],
        txns_last_hour=context["txns_last_hour"],
        txns_today=context["txns_today"],
        payer_seen_payee_before=payer_has_paid(payee.vpa, tx.sender),
    )

    prob = float(model_or_503().predict_proba(to_frame(features))[0][1])
    risk_score = int(round(prob * 100))
    model_flag = prob >= DECISION_THRESHOLD

    # The model decides. The two hard rules stay as a floor because a payment
    # near the top of what UPI permits, or an obvious velocity spike, should
    # never be waved through on a model's say-so.
    #
    # 70000 used to be written here as a bare number and it was doing more work
    # than it looked like. The simulator's amounts top out around Rs 61,000 -
    # 3 rows in 120,000 above Rs 50,000 and NONE above Rs 70,000 - so the model
    # has never seen the top 30% of the legal UPI range and its prediction is
    # flat at 0.4034 from Rs 5,000 to Rs 1,00,000. This rule was the only thing
    # separating a Rs 1 lakh drain from a Rs 5,000 payment. The simulator now
    # covers the full legal range (see ml/dataset.py), so the model can see the
    # gradient itself - but the floor stays, expressed against the cap rather
    # than as a magic number, because the cost of missing a maxed-out transfer
    # is the whole daily limit.
    near_the_upi_ceiling = tx.amount >= 0.7 * standard_cap()
    risk = 1 if (model_flag or near_the_upi_ceiling or tx.velocity_score > 7) else 0

    # The full uuid, not hex[:6]. Six hex characters is 24 bits: by the birthday
    # bound there is a 1% chance of a collision by about 580 payments and a 50%
    # chance by about 4,800 - and transaction_id is the PRIMARY KEY of
    # scored_transactions written with INSERT OR REPLACE, so a collision did not
    # error, it silently overwrote somebody's payment record. It also made the
    # ids short enough to enumerate.
    tx_id = f"tx_{uuid.uuid4().hex}"

    transaction_data = {
        "transaction_id": tx_id,
        "amount": tx.amount,
        "device_score": tx.device_score,
        "location_score": tx.location_score,
        "velocity_score": tx.velocity_score,
        "sender": tx.sender,
        "receiver": tx.receiver,
        "timestamp": tx.timestamp,
        "risk": risk,
        "risk_score": risk_score
    }

    save_transaction(transaction_data)

    add_connection(tx.sender, tx.receiver)

    personalized_profile = get_behavior_profile(tx.sender)
    personalized_assessment = None
    if personalized_profile is not None:
        history = get_user_transactions(tx.sender)
        personalized_assessment = evaluate_personalized_risk(
            profile=personalized_profile,
            history=history,
            amount=tx.amount,
            merchant=tx.receiver,
            timestamp=tx.timestamp,
        )

    return {
        "transaction_id": tx_id,
        "risk": risk,
        "risk_score": risk_score,
        "probability": round(prob, 5),
        "threshold": round(DECISION_THRESHOLD, 5),
        "decided_by": (
            "model" if model_flag
            else "rule:near_upi_ceiling" if near_the_upi_ceiling
            else "rule:velocity" if risk
            else "none"
        ),
        # Which ceiling the rule was measured against, so the number above is
        # not another unexplained constant in the response.
        "upi_per_transaction_cap": standard_cap(),
        "model": MODEL_METRICS.get("selected", {}).get("model"),
        "fpr_budget": FPR_BUDGET,
        # The features as JSON, which means null where the pipeline holds NaN.
        # `features` itself is untouched - the model above was handed the real
        # vector - and payee_history_available still says in the response
        # whether the payee row was read at all, so an unavailable feature
        # stays distinguishable from a measured zero.
        "features": json_safe(features),
        "personalized_assessment": personalized_assessment
    }


# --------------------------------------------------
# Fraud Heatmap
# --------------------------------------------------

@app.get("/heatmap")
def heatmap(user: str = Depends(get_current_user)):
    """The caller's own scored payments.

    Two bugs here. It was unauthenticated and unscoped, so it returned every
    user's payment amounts to anyone who asked - and the Python service is
    reachable directly, not only through Express. And it returned the binary
    `risk` flag but no score, so the frontend invented one with
    Math.random(): the y-axis of the "Fraud Activity Heatmap" was noise, and
    every reload moved the points. risk_score is stored on the row; return it.
    """
    df = get_all_transactions(sender=user)

    if len(df) < 2:
        return {"error": "Not enough transactions"}

    return {
        "amount": df["amount"].tolist(),
        "risk": df["risk"].tolist(),
        "risk_score": df["risk_score"].tolist(),
    }


# --------------------------------------------------
# SHAP Explainability
# --------------------------------------------------

@app.get("/explain/{tx_id}")
def explain(tx_id: str, user: str = Depends(get_current_user)):

    tx = get_transaction(tx_id)

    # Ownership, not just existence. Transaction ids are guessable and this
    # endpoint returns the amount, the payee and the full feature vector, so
    # without the check any logged-in user could read any other user's
    # payments one id at a time. 404 rather than 403: a 403 would confirm the
    # id exists.
    if tx is None or (tx.get("sender") or "") != user:
        raise HTTPException(status_code=404, detail="Transaction Not Found")

    payer_profile = get_behavior_profile(tx.get("sender", ""))
    payee = assess_payee(payee_key(tx.get("receiver", ""), tx.get("receiver", "")))

    context = _payer_context(tx.get("sender") or "", tx.get("timestamp") or "")
    features = build_features(
        amount=tx["amount"],
        timestamp=tx.get("timestamp"),
        profile=payer_profile,
        reputation=payee.as_dict(),
        seconds_since_last_txn=context["seconds_since_last_txn"],
        txns_last_hour=context["txns_last_hour"],
        txns_today=context["txns_today"],
        payer_seen_payee_before=payer_has_paid(payee.vpa, tx.get("sender") or ""),
    )

    try:
        shap_values = get_explainer()(to_frame(features).to_numpy())
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "transaction_id": tx_id,
        "features": MODEL_FEATURES,
        # Attributions for a vector that can carry NaN can themselves be
        # non-finite, and this response has the same JSON boundary as /predict.
        "shap_values": json_safe(shap_values.values.tolist()),
        "model": MODEL_METRICS.get("selected", {}).get("model"),
    }


# --------------------------------------------------
# Fraud Graph
# --------------------------------------------------

@app.get("/fraud-graph")
def fraud_graph(user: str = Depends(get_current_user)):
    """The persisted payer -> payee graph, with payment counts on each edge."""
    edges = load_edges()
    return {
        "edges": [
            {"user": e.payer, "merchant": e.payee, "payments": e.payments}
            for e in edges
        ]
    }


# --------------------------------------------------
# Fraud Rings
# --------------------------------------------------

@app.get("/fraud-rings")
def fraud_rings(user: str = Depends(get_current_user)):
    """Addresses that share a payer pool AND show the collection shape.

    The previous implementation walked every node in an in-memory graph and
    reported any with three or more neighbours, so it reported payers as
    merchants and flagged every popular shop.
    """
    rings = detect_rings(load_edges())
    return {
        "rings": [
            {
                "merchant": r.payees[0],
                "payees": r.payees,
                "users": r.shared_payers,
                "overlap": r.overlap,
                "total_payments": r.total_payments,
                "reason": r.reason,
            }
            for r in rings
        ]
    }


# --------------------------------------------------
# Temporal Fraud
# --------------------------------------------------

@app.get("/temporal-patterns")
def temporal_api(user: str = Depends(get_current_user)):
    # Was unauthenticated and returned every user's hourly payment pattern.
    df = get_all_transactions(sender=user)

    if df.empty:
        return {"error": "No transactions"}

    return temporal_patterns(df)


# --------------------------------------------------
# Behavioral Biometrics
# --------------------------------------------------

@app.get("/behavior/{tx_id}")
def behavior(tx_id: str, user: str = Depends(get_current_user)):

    tx = get_transaction(tx_id)

    if tx is None or (tx.get("sender") or "") != user:
        raise HTTPException(status_code=404, detail="Transaction Not Found")

    label = behavior_score(tx["velocity_score"], tx["device_score"])
    score = behaviour_risk(tx["velocity_score"], tx["device_score"])

    return {
        "transaction_id": tx_id,
        "behavior_risk": label,
        # The number the label came from, so the caller can see the margin
        # rather than only which side of a threshold it fell.
        "behavior_score": round(score, 3),
        "components": {
            "velocity_normalised": round(normalised_velocity(tx["velocity_score"]), 3),
            "device_score": float(tx["device_score"]),
        },
    }


# --------------------------------------------------
# Model Drift
# --------------------------------------------------

@app.get("/model-drift")
def model_drift(user: str = Depends(get_current_user)):
    """Drift is a property of the deployed model, so this is deliberately
    global rather than per-user.

    Three things were wrong. It read the binary `risk` flag, so a drift that
    moved scores from 45 to 65 without crossing the threshold was invisible.
    It used ten rows a side, where the sampling noise of a proportion is
    larger than the 0.3 threshold it was tested against. And when there was
    too little data it returned {"status": ...} with no `drift_status` key, so
    the UI's `drift_status || "Model Stable"` printed a green "Model Stable" -
    the reassuring answer - for a check that had not run.
    """
    df = get_all_transactions(limit=2000)

    scores = pd.to_numeric(df.get("risk_score"), errors="coerce").dropna().tolist()
    half = len(scores) // 2
    report = drift_report(scores[:half], scores[half:])

    # drift_status is always present now, including for the inconclusive case.
    return {
        "drift_status": report["status"],
        "detail": report.get("detail"),
        "conclusive": report.get("conclusive", False),
        "mean_before": report.get("mean_before"),
        "mean_after": report.get("mean_after"),
        "shift": report.get("shift"),
        "sigmas": report.get("sigmas"),
        "n_before": report.get("n_before"),
        "n_after": report.get("n_after"),
    }


# --------------------------------------------------
# GNN Fraud Detection
# --------------------------------------------------

@app.get("/gnn-fraud-detection")
def gnn_detection(user: str = Depends(get_current_user)):
    """Graph anomalies in the payer -> payee network.

    Kept at this path so the existing UI keeps working, but this is graph
    analysis, not a graph neural network: nothing in this repository trains
    one. Each result carries the reason it was returned, which the old
    degree >= 3 rule could not do (it returned the most popular merchants).
    """
    summary = graph_summary()
    return {
        "method": "bipartite graph analysis",
        "suspicious_nodes": [d["node"] for d in summary["suspicious"]],
        "details": summary["suspicious"],
        "graph": {
            "payers": summary["payers"],
            "payees": summary["payees"],
            "edges": summary["edges"],
            "components": summary["components"],
        },
    }


# --------------------------------------------------
# Statement Profiling
# --------------------------------------------------

# One upload previously inserted 250,000 rows and grew the database to
# 147 MB. Cap both the file and the row count.
MAX_STATEMENT_BYTES = 10 * 1024 * 1024
MAX_STATEMENT_ROWS = 20_000

# Filenames legal on both filesystems this runs on, and no path at all.
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]")


def _safe_filename(name: str | None) -> str:
    """A client-supplied filename, reduced to a name.

    PurePosixPath and PureWindowsPath both, because the header is whatever the
    sender wrote: a Windows client sends backslashes, and a server on Linux
    would treat "..\\..\\x" as one long filename while a server on Windows
    would treat it as a path.
    """
    candidate = (name or "").strip()
    candidate = PureWindowsPath(PurePosixPath(candidate).name).name
    candidate = _SAFE_FILENAME.sub("_", candidate).lstrip(".")
    return candidate[:120] or "statement"

@app.post("/statement/upload")
async def upload_statement(
    file: UploadFile = File(...),
    retain_source: bool = Form(False),
    user_id: str = Depends(get_current_user),
):
    """The statement belongs to whoever uploaded it. A user_id in the form body
    is ignored so one account cannot write into another's history."""

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(content) > MAX_STATEMENT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Statement exceeds the {MAX_STATEMENT_BYTES // (1024 * 1024)} MB limit",
        )

    try:
        parsed = parse_statement_file(file.filename or "statement.pdf", content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # The library's own words ("Stream has ended unexpectedly") described
        # the server's internals to the client and called a corrupt upload a
        # 500 - our failure rather than an unreadable file. Logged here, where
        # it is useful, and answered with what the caller can act on.
        print(f"[statement] parse failed for {file.filename!r}: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=400,
            detail="This file could not be read as a statement. Export it again "
                   "from your bank or UPI app and upload the original PDF or CSV.",
        ) from exc

    transactions = parsed["transactions"][:MAX_STATEMENT_ROWS]
    if len(parsed["transactions"]) > MAX_STATEMENT_ROWS:
        parsed["warnings"].append(
            f"Statement truncated to the first {MAX_STATEMENT_ROWS} transactions."
        )
    if not transactions:
        return {
            "user_id": user_id,
            "statement_id": None,
            "source_type": parsed["source_type"],
            "transactions_extracted": 0,
            "warnings": parsed["warnings"],
            "profile_created": False,
        }

    statement_id = f"stmt_{uuid.uuid4().hex[:8]}"
    save_statement_transactions(
        user_id=user_id,
        statement_id=statement_id,
        source_type=parsed["source_type"],
        transactions=transactions,
    )

    history = get_user_transactions(user_id)
    profile = generate_behavior_profile(history.to_dict(orient="records"))
    save_behavior_profile(
        user_id=user_id,
        source_type=parsed["source_type"],
        profile=profile,
        transaction_count=int(len(history)),
    )

    if retain_source:
        uploads_dir = Path("data") / "uploaded_statements"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        # The filename comes from the multipart header, which is to say from
        # whoever sent the request. It was concatenated into the path as given,
        # so "../../x.csv" was a path and not a name: with the right directory
        # in place that writes outside the uploads folder, and without one it
        # raised FileNotFoundError and returned an unexplained 500.
        (uploads_dir / f"{user_id}_{statement_id}_{_safe_filename(file.filename)}").write_bytes(content)

    return {
        "user_id": user_id,
        "statement_id": statement_id,
        "source_type": parsed["source_type"],
        "transactions_extracted": len(transactions),
        "extracted_transactions": transactions,
        "warnings": parsed["warnings"],
        "profile_created": True,
        "profile": get_behavior_profile(user_id),
    }


@app.get("/profiles/me")
def get_my_profile(user: str = Depends(get_current_user)):
    profile = get_behavior_profile(user)
    if profile is None:
        raise HTTPException(status_code=404, detail="Behavior profile not found")
    return profile


MAX_STATEMENT_PAGE = 2000


@app.get("/statement-transactions")
def statement_transactions(
    limit: int = MAX_STATEMENT_PAGE,
    offset: int = 0,
    user: str = Depends(get_current_user),
):
    """The signed-in user's statement lines, paged.

    Capped because a large statement previously went to the browser in one
    response and the profile page had to paginate a quarter of a million rows
    in JavaScript.
    """
    limit = max(1, min(int(limit or MAX_STATEMENT_PAGE), MAX_STATEMENT_PAGE))
    offset = max(0, int(offset or 0))

    df = get_user_transactions(user)
    total = int(len(df))
    page = df.iloc[offset:offset + limit].fillna("")

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "truncated": total > offset + limit,
        "transactions": page.to_dict(orient="records"),
    }


@app.post("/personalized-risk-check")
def personalized_risk_check(
    payload: PersonalizedRiskCheck, user: str = Depends(get_current_user)
):
    profile = get_behavior_profile(user)
    history = get_user_transactions(user)

    result = evaluate_personalized_risk(
        profile=profile,
        history=history,
        amount=payload.amount,
        merchant=payload.merchant,
        timestamp=payload.timestamp,
        upi_id=payload.upi_id,
        location=payload.location,
    )

    return {
        "user_id": user,
        **result,
    }

@app.get("/transactions")
def get_transactions(user: str = Depends(get_current_user)):
    df = get_user_transactions(user)
    if df is None or df.empty:
        return []
        
    profile = get_behavior_profile(user)
    txs = []
    # Return last 100 for the monitor
    for _, row in df.tail(100).iterrows():
        amount = float(row.get("amount", 0))
        merchant = str(row.get("merchant", "UNKNOWN"))
        ts = str(row.get("timestamp", ""))
        upi_id = str(row.get("upi_id", ""))
        
        # Real evaluation
        risk_result = evaluate_personalized_risk(
            profile=profile,
            history=df,
            amount=amount,
            merchant=merchant,
            timestamp=ts,
            upi_id=upi_id,
            # This row is already in `df`; without saying so the same-day
            # count included it twice and reported one payment too many.
            already_recorded=True,
        )
        
        score = risk_result.get("risk_score", 10)
        
        txs.append({
            "transaction_id": str(row.get("id", "")),
            "amount": amount,
            # Derived from `score`, not measured. Named so, because the UI
            # was labelling them "Scores (Dev/Loc/Vel)" as if they were three
            # independent signals; they are perfectly collinear with the score
            # already shown.
            "derived_from_score": True,
            "device_score": round(score / 100 * 0.8, 2),
            "location_score": round(score / 100 * 0.6, 2),
            "velocity_score": round(score / 10, 2),
            "sender": user,
            "receiver": merchant,
            "timestamp": ts,
            # The band comes from the canonical mapping, never from a local
            # comparison. This row used to publish `risk = score > 50`, a
            # fourth threshold that belonged to nothing: the monitor rendered
            # it as BLOCKED/APPROVED, so a score of 60 read as BLOCKED where
            # the payment path calls 60 a STEP_UP, and a score of 30 read as
            # APPROVED where the payment path calls 30 a WARN. Same number,
            # two vocabularies, no shared definition.
            "verdict": verdict_from_score(score),
            # Kept for the older monitor table, and derived so it cannot
            # disagree: anything the canonical bands say needs a human step is
            # flagged, everything else is not.
            "risk": 1 if verdict_from_score(score) in {"STEP_UP", "BLOCK"} else 0,
            "risk_score": score
        })
    return txs

# --------------------------------------------------
# Startup guard: a duplicated path silently shadows the
# later definition (FastAPI serves the first match), which
# is how the auth-protected routes became dead code.
# --------------------------------------------------

def _assert_no_duplicate_routes() -> None:
    seen: set[tuple] = set()
    for r in app.routes:
        path = getattr(r, "path", None)
        methods = tuple(sorted(getattr(r, "methods", None) or ()))
        if path is None:
            continue
        key = (path, methods)
        if key in seen:
            raise RuntimeError(f"Duplicate route registered: {methods} {path}")
        seen.add(key)


_assert_no_duplicate_routes()


# --------------------------------------------------
# Pre-payment payee check
# --------------------------------------------------

@app.get("/payee/intents")
def payee_intents():
    """The stated-purpose options, and what happens to a shared message.

    The UI reads the list from here so it cannot drift from what the server
    actually scores, and the privacy line is served with it so the promise and
    the implementation live in the same place.
    """
    return {
        "intents": [{"id": key, "label": label} for key, label in INTENTS.items()],
        "message_handling": (
            "Sharing the message is optional. It is scored in memory and "
            "discarded - the text is never written to disk or logged, and only "
            "the matched pattern names appear in the result."
        ),
        "language_coverage": ["English", "romanised Hindi"],
    }


@app.post("/payee/check")
def payee_check(payload: PayeeCheckRequest, user: str = Depends(get_current_user)):
    """Score a payee BEFORE any money moves.

    Everything else in this API scores the payer against their own history,
    which cannot see a first-time victim paying a scammer. This looks at the
    address being paid.
    """
    if not payload.payload.strip():
        raise HTTPException(status_code=400, detail="Nothing to check")

    # Everything this token is entitled to read, resolved here and handed over.
    # check_payee performs the whole assembly - every evidence family including
    # the behavioural classifier, one combination rule, one verdict.
    #
    # This endpoint used to run the payer-side rules separately and reconcile
    # the two results afterwards with `if decision == "APPROVE" and risk_level
    # == "HIGH": decision = "WARN"`. That was two scoring systems on two
    # different scales meeting in an if-statement: the damped-max rule and the
    # agreement bonus never saw the payer's score, so it could not corroborate
    # anything, and it could only ever nudge one band. It is now a family like
    # the rest, and the reconciliation is gone.
    profile = get_behavior_profile(user)
    return check_payee(
        payload.payload,
        payer_id=user,
        amount=payload.amount,
        intent=payload.intent,
        message=payload.message,
        profile=profile,
        history=get_user_transactions(user) if profile else None,
        timestamp=pd.Timestamp.now().isoformat(),
    )


@app.get("/chat/status")
def chat_status():
    """Whether the assistant has a model behind it.

    The UI needs to say "not configured" rather than offering a chat box that
    answers everything with an error.
    """
    return {"available": chat_configured()}


@app.post("/chat")
def chat(payload: ChatRequest, user: str = Depends(get_current_user)):
    """Explain, never decide.

    The assistant has no tools and cannot act. The facts it sees are assembled
    server-side from this token's own profile, so a client cannot widen its own
    access by asking; see backend/app/services/chat.py for the reasoning.
    """
    reply = chat_answer(
        question=payload.message,
        user=user,
        history=[t.model_dump() for t in payload.history],
        # Looked up here from the token. Never taken from the request body.
        profile=get_behavior_profile(user),
        check_result=payload.check_result,
    )
    return reply.as_dict()


@app.post("/payee/report")
def payee_report(payload: PayeeReportRequest, user: str = Depends(get_current_user)):
    """Report a payee. Reports are what turn one person's bad experience into
    a signal for everyone else."""
    if not payload.vpa.strip():
        raise HTTPException(status_code=400, detail="No address given")
    count = report_payee(payload.vpa, reporter=user, reason=payload.reason or "")
    return {"vpa": payload.vpa, "reports": count}


@app.post("/payee/confirm")
def payee_confirm(payload: PayeeCheckRequest, user: str = Depends(get_current_user)):
    """Record that the payer went ahead. This is what grows the reputation
    graph: without it the store only ever knows what was uploaded."""
    profile = get_behavior_profile(user)
    result = check_payee(
        payload.payload,
        payer_id=user,
        amount=payload.amount,
        intent=payload.intent,
        message=payload.message,
        profile=profile,
        history=get_user_transactions(user) if profile else None,
        timestamp=pd.Timestamp.now().isoformat(),
    )
    vpa = result["payee"]["key"]
    if vpa and payload.amount:
        record_payment(vpa, payer_id=user, amount=payload.amount,
                       display_name=result["payee"]["display_name"])
    return {"recorded": bool(vpa and payload.amount), "payee": vpa}


if __name__ == "__main__":
    import uvicorn

    # The import STRING, not the app object, and reload=True.
    #
    # `uvicorn.run(app, ...)` cannot reload - uvicorn needs a module path to
    # re-import, and silently runs without reloading when handed an object. So
    # `npm run dev` started a server that served whatever the code was at boot
    # and never noticed another change: a new route answered 404 while /health
    # kept returning 200, which looks like a routing bug and is not one.
    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        # data/ churns constantly (SQLite journal files) and models/ is written
        # by the trainer; watching either restarts the server mid-request.
        reload_dirs=["backend"],
    )

