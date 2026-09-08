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

from backend.app.services.behavioral_biometrics import behavior_score
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
from backend.models.ensemble_model import load_model

# GNN
from backend.advanced_ai.gnn_fraud_detector import gnn_risk


app = FastAPI()

# --------------------------------------------------
# Load ML Model
# --------------------------------------------------

model = load_model()


# --------------------------------------------------
# SHAP Setup (FIXED)
# --------------------------------------------------

background_data = np.random.rand(50, 5)

def shap_predict(X):
    return model.predict_proba(X)[:, 1]

explainer = shap.Explainer(shap_predict, background_data)


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

    user_id: str
    amount: float
    merchant: str
    timestamp: str
    upi_id: str | None = None
    location: str | None = None

class UserAuth(BaseModel):
    username: str
    password: str

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
    user_id = f"usr_{uuid.uuid4().hex[:8]}"
    hashed = hash_password(user.password)
    success = create_user(user_id, user.username, hashed)
    if not success:
        raise HTTPException(status_code=400, detail="Username already exists")
    token = create_token(user_id)
    return {"message": "User created", "token": token, "user_id": user_id, "username": user.username}

@app.post("/auth/login")
def login(user: UserAuth):
    db_user = get_user_by_username(user.username)
    if not db_user or not verify_password(user.password, db_user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    token = create_token(db_user["id"])
    return {"token": token, "user_id": db_user["id"], "username": db_user["username"]}



# --------------------------------------------------
# Root
# --------------------------------------------------

@app.get("/")
def home():
    return {"message": "Edge AI UPI Behaviour Risk System Running"}


@app.get("/health")
def health():
    return {"status": "ok"}


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

    df = get_all_transactions()

    if df.empty:

        rolling_avg_amount = tx.amount
        rolling_txn_count = 1
        time_gap = 100

    else:

        rolling_avg_amount = df["amount"].tail(5).mean()
        rolling_txn_count = len(df.tail(5))

        try:
            last_time = pd.to_datetime(df.iloc[-1]["timestamp"])
            time_gap = (current_time - last_time).total_seconds()
        except:
            time_gap = 100

    # ML Features
    features = [
        tx.amount,
        is_night,
        rolling_avg_amount,
        rolling_txn_count,
        time_gap
    ]

    prob = float(model.predict_proba([features])[0][1])

    # normalize probability
    prob = max(0.05, min(prob, 0.95))

    risk_score = int(prob * 100)

    if tx.amount > 70000 or tx.velocity_score > 7:
        risk = 1
    else:
        risk = 1 if risk_score >= 70 else 0

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

    df = get_all_transactions()

    if df.empty:
        rolling_avg = tx["amount"]
        rolling_txn = 1
        time_gap = 100
        is_night = 0
    else:
        rolling_avg = df["amount"].tail(5).mean()
        rolling_txn = len(df.tail(5))
        time_gap = 100
        is_night = 0

    features = np.array([[

        tx["amount"],
        is_night,
        rolling_avg,
        rolling_txn,
        time_gap

    ]])

    shap_values = explainer(features)

    return {
        "transaction_id": tx_id,
        "features": [
            "amount",
            "is_night",
            "rolling_avg",
            "rolling_txn_count",
            "time_gap"
        ],
        "shap_values": shap_values.values.tolist()
    }


# --------------------------------------------------
# Fraud Graph
# --------------------------------------------------

@app.get("/fraud-graph")
def fraud_graph(user: str = Depends(get_current_user)):

    edges = get_all_edges()

    return {"edges": edges}


# --------------------------------------------------
# Fraud Rings
# --------------------------------------------------

@app.get("/fraud-rings")
def fraud_rings():

    rings = detect_fraud_rings()

    return {"rings": rings}


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

    result = behavior_score(
        tx["velocity_score"],
        tx["device_score"]
    )

    return {
        "transaction_id": tx_id,
        "behavior_risk": result
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

    edges = get_all_edges()

    suspicious = gnn_risk(edges)

    return {"suspicious_nodes": suspicious}


# --------------------------------------------------
# Statement Profiling
# --------------------------------------------------

@app.post("/statement/upload")
async def upload_statement(
    user_id: str = Form(...),
    file: UploadFile = File(...),
    retain_source: bool = Form(False),
):

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        parsed = parse_statement_file(file.filename or "statement.pdf", content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Statement parsing failed: {exc}") from exc

    transactions = parsed["transactions"]
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


@app.post("/personalized-risk-check")
def personalized_risk_check(payload: PersonalizedRiskCheck):

    profile = get_behavior_profile(payload.user_id)
    history = get_user_transactions(payload.user_id)

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
        "user_id": payload.user_id,
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

