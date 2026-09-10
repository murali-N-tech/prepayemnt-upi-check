import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from fastapi import FastAPI, HTTPException
from fastapi import File, Form, UploadFile
from pydantic import BaseModel
import uuid
import numpy as np
import pandas as pd
import shap
from pathlib import Path
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
from backend.app.services.intent import INTENTS
from backend.app.services.payee_check import check_payee
from backend.app.services.upi_verify import (
    is_configured as upi_verifier_configured,
    verification_required as upi_verification_required,
    verify_vpa,
)
from backend.app.services.payee_reputation import record_payment, report_payee

from backend.app.services.behavioral_biometrics import (
    behavior_score,
    behaviour_risk,
    normalised_velocity,
)
from backend.app.services.temporal_gnn import temporal_patterns
from backend.app.services.drift_monitor import detect_drift

from backend.app.core.security import hash_password, verify_password, create_token, verify_token
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


class PersonalizedRiskCheck(BaseModel):

    amount: float
    merchant: str
    timestamp: str
    upi_id: str | None = None
    location: str | None = None

class UserAuth(BaseModel):
    username: str
    password: str


class PayeeCheckRequest(BaseModel):
    """`payload` is a scanned QR, a pasted UPI ID, or a phone number."""
    payload: str
    amount: float | None = None
    # What the payer says they are doing. One of intent.INTENTS.
    intent: str | None = None
    # The message that prompted this payment, if the payer chose to share it.
    # Opt-in, scored in memory, and never stored - see /payee/intents.
    message: str | None = None


class PayeeReportRequest(BaseModel):
    vpa: str
    reason: str | None = None

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

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

    user_id = f"usr_{uuid.uuid4().hex[:8]}"
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
def predict(tx: Transaction):

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
    df = get_all_transactions(sender=tx.sender, limit=50)

    # No prior payment is not the same as "one second ago". Default to a long
    # gap so an absent history does not read as a rapid-fire burst.
    NO_PRIOR_GAP = 86_400.0

    if df.empty:
        rolling_avg_amount = tx.amount
        rolling_txn_count = 1
        time_gap = NO_PRIOR_GAP
    else:
        recent = df.tail(5)
        rolling_avg_amount = float(recent["amount"].mean())
        rolling_txn_count = int(len(recent))

        time_gap = NO_PRIOR_GAP
        last_time = pd.to_datetime(df.iloc[-1]["timestamp"], errors="coerce", utc=True)
        now = pd.to_datetime(current_time, errors="coerce", utc=True)
        if pd.notna(last_time) and pd.notna(now):
            delta = (now - last_time).total_seconds()
            # Clamp: a clock skew or an out-of-order timestamp must not become
            # a negative gap, which reads as the strongest velocity signal there is.
            time_gap = float(min(max(delta, 1.0), NO_PRIOR_GAP))

    # Payments already made today by this payer, for the velocity feature.
    txns_today = 1
    if not df.empty:
        day = pd.to_datetime(df["timestamp"], errors="coerce", utc=True).dt.date
        today = pd.to_datetime(current_time, errors="coerce", utc=True)
        if pd.notna(today):
            txns_today = int((day == today.date()).sum()) + 1

    # The model is trained on these exact features (backend/ml/features.py is
    # the single mapping, so training and serving cannot drift apart).
    payer_profile = get_behavior_profile(tx.sender)
    payee = assess_payee(payee_key(tx.receiver, tx.receiver))

    features = build_features(
        amount=tx.amount,
        timestamp=tx.timestamp,
        profile=payer_profile,
        reputation=payee.as_dict(),
        seconds_since_last_txn=time_gap,
        txns_last_hour=tx.velocity_score,
        txns_today=txns_today,
    )

    prob = float(model_or_503().predict_proba(to_frame(features))[0][1])
    risk_score = int(round(prob * 100))
    model_flag = prob >= DECISION_THRESHOLD

    # The model decides. The two hard rules stay as a floor because a very
    # large amount or an obvious velocity spike should never be waved through
    # on a model's say-so.
    risk = 1 if (model_flag or tx.amount > 70000 or tx.velocity_score > 7) else 0

    tx_id = f"tx_{uuid.uuid4().hex[:6]}"

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
        "decided_by": "model" if model_flag else ("rule" if risk else "none"),
        "model": MODEL_METRICS.get("selected", {}).get("model"),
        "fpr_budget": FPR_BUDGET,
        "features": features,
        "personalized_assessment": personalized_assessment
    }


# --------------------------------------------------
# Fraud Heatmap
# --------------------------------------------------

@app.get("/heatmap")
def heatmap():

    df = get_all_transactions()

    if len(df) < 2:
        return {"error": "Not enough transactions"}

    return {
        "amount": df["amount"].tolist(),
        "risk": df["risk"].tolist()
    }


# --------------------------------------------------
# SHAP Explainability
# --------------------------------------------------

@app.get("/explain/{tx_id}")
def explain(tx_id: str):

    tx = get_transaction(tx_id)

    if tx is None:
        raise HTTPException(status_code=404, detail="Transaction Not Found")

    payer_profile = get_behavior_profile(tx.get("sender", ""))
    payee = assess_payee(payee_key(tx.get("receiver", ""), tx.get("receiver", "")))

    features = build_features(
        amount=tx["amount"],
        timestamp=tx.get("timestamp"),
        profile=payer_profile,
        reputation=payee.as_dict(),
        txns_last_hour=tx.get("velocity_score", 0),
    )

    try:
        shap_values = get_explainer()(to_frame(features).to_numpy())
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "transaction_id": tx_id,
        "features": MODEL_FEATURES,
        "shap_values": shap_values.values.tolist(),
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
def temporal_api():

    df = get_all_transactions()

    if df.empty:
        return {"error": "No transactions"}

    return temporal_patterns(df)


# --------------------------------------------------
# Behavioral Biometrics
# --------------------------------------------------

@app.get("/behavior/{tx_id}")
def behavior(tx_id: str):

    tx = get_transaction(tx_id)

    if tx is None:
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

    df = get_all_transactions()

    if len(df) < 20:
        return {"status": "Not enough data"}

    old_scores = df["risk"][:10]
    new_scores = df["risk"][-10:]

    drift = detect_drift(old_scores, new_scores)

    return {"drift_status": drift}


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
        raise HTTPException(status_code=500, detail=f"Statement parsing failed: {exc}") from exc

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
        output_name = f"{user_id}_{statement_id}_{file.filename}"
        (uploads_dir / output_name).write_bytes(content)

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
            upi_id=upi_id
        )
        
        score = risk_result.get("risk_score", 10)
        
        txs.append({
            "transaction_id": str(row.get("id", "")),
            "amount": amount,
            "device_score": round(score / 100 * 0.8, 2), # derive some mock metrics based on actual score
            "location_score": round(score / 100 * 0.6, 2),
            "velocity_score": round(score / 10, 2),
            "sender": user,
            "receiver": merchant,
            "timestamp": ts,
            "risk": 1 if score > 50 else 0,
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

    result = check_payee(
        payload.payload,
        payer_id=user,
        amount=payload.amount,
        intent=payload.intent,
        message=payload.message,
    )

    # Fold the payer's own baseline in when there is one, so a payment that is
    # odd FOR THEM still surfaces even if the payee looks fine.
    profile = get_behavior_profile(user)
    if profile and payload.amount:
        history = get_user_transactions(user)
        personal = evaluate_personalized_risk(
            profile=profile,
            history=history,
            amount=payload.amount,
            merchant=result["payee"]["display_name"] or result["payee"]["vpa"] or "",
            timestamp=pd.Timestamp.now().isoformat(),
            upi_id=result["payee"]["vpa"],
        )
        result["payer_behaviour"] = personal
        # A payee-side BLOCK is never softened by the payer looking normal.
        if result["decision"] == "APPROVE" and personal["risk_level"] == "HIGH":
            result["decision"] = "WARN"
            result["headline"] = "Unusual for you, even though the payee looks fine"
    else:
        result["payer_behaviour"] = None

    return result


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
    result = check_payee(
        payload.payload,
        payer_id=user,
        amount=payload.amount,
        intent=payload.intent,
        message=payload.message,
    )
    vpa = result["payee"]["key"]
    if vpa and payload.amount:
        record_payment(vpa, payer_id=user, amount=payload.amount,
                       display_name=result["payee"]["display_name"])
    return {"recorded": bool(vpa and payload.amount), "payee": vpa}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

