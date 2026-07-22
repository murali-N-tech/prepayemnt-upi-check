import streamlit as st
import requests
import pandas as pd
import numpy as np
import networkx as nx
import matplotlib.pyplot as plt
from datetime import datetime

API = "http://127.0.0.1:8000"

st.set_page_config(page_title="Edge AI UPI Fraud System", layout="wide")

st.title("🚨 Edge AI UPI Behaviour Risk System")

st.sidebar.title("Navigation")

page = st.sidebar.selectbox(
    "Select Page",
    [
        "Statement Profiling",
        "Pre-Payment Risk Check",
        "Fraud Detection",
        "Fraud Network Graph",
        "Fraud Rings",
        "Fraud Heatmap",
        "Explainability",
        "Fraud Alerts",
        "System Monitor"
    ]
)

# ------------------------------------------------
# Statement Profiling
# ------------------------------------------------

if page == "Statement Profiling":

    st.header("Statement Upload and Behaviour Profile Generation")
    st.write(
        "Upload a text-based UPI or bank statement PDF to extract transaction features and build a personalized payment profile."
    )

    col1, col2 = st.columns([2, 1])

    with col1:
        profile_user_id = st.text_input("Profile User ID", key="profile_user_id")

    with col2:
        retain_source = st.checkbox("Retain original file", value=False)

    statement_file = st.file_uploader(
        "Upload statement",
        type=["pdf", "csv"],
        help="CSV is useful for testing. For PDF, text-based statements work best in this version.",
    )

    if st.button("Generate Behaviour Profile"):
        if not profile_user_id or statement_file is None:
            st.warning("Provide a user ID and upload a statement file.")
        else:
            try:
                response = requests.post(
                    f"{API}/statement/upload",
                    data={
                        "user_id": profile_user_id,
                        "retain_source": str(retain_source).lower(),
                    },
                    files={
                        "file": (
                            statement_file.name,
                            statement_file.getvalue(),
                            statement_file.type or "application/octet-stream",
                        )
                    },
                )

                if response.status_code != 200:
                    st.error(response.text)
                else:
                    result = response.json()

                    st.success(
                        f"Profile updated for {result['user_id']} with {result['transactions_extracted']} extracted transactions."
                    )

                    if result.get("warnings"):
                        for warning in result["warnings"]:
                            st.warning(warning)

                    profile = result.get("profile")
                    if profile:
                        metrics = st.columns(4)
                        metrics[0].metric("Transactions", profile.get("transaction_count", 0))
                        metrics[1].metric("Average Amount", profile.get("avg_amount", 0))
                        metrics[2].metric("Max Amount", profile.get("max_amount", 0))
                        metrics[3].metric("Most Active Hour", profile.get("most_active_hour", "-"))

                        st.subheader("Favorite Merchants")
                        st.write(profile.get("favorite_merchants", []))

                        st.subheader("Merchant Frequency")
                        freq = profile.get("merchant_frequency", {})
                        if freq:
                            st.bar_chart(pd.DataFrame.from_dict(freq, orient="index", columns=["count"]))

                        st.subheader("Monthly Totals")
                        monthly = profile.get("monthly_totals", {})
                        if monthly:
                            st.line_chart(pd.Series(monthly))

            except Exception as e:
                st.error(f"Profile generation failed: {e}")


# ------------------------------------------------
# Personalized Risk Check
# ------------------------------------------------

elif page == "Pre-Payment Risk Check":

    st.header("Personalized Pre-Payment Risk Check")
    st.write(
        "This compares a proposed payment against the user's historical behaviour profile extracted from uploaded statements."
    )

    col1, col2, col3 = st.columns(3)

    with col1:
        risk_user_id = st.text_input("User ID", key="risk_user_id")
    with col2:
        risk_merchant = st.text_input("Merchant", key="risk_merchant")
    with col3:
        risk_amount = st.number_input("Amount", min_value=0.0, key="risk_amount")

    col4, col5 = st.columns(2)

    with col4:
        risk_upi_id = st.text_input("UPI ID (optional)")
    with col5:
        risk_location = st.text_input("Location (optional)")

    if st.button("Run Personalized Check"):
        payload = {
            "user_id": risk_user_id,
            "amount": risk_amount,
            "merchant": risk_merchant,
            "timestamp": str(datetime.now()),
            "upi_id": risk_upi_id or None,
            "location": risk_location or None,
        }

        try:
            response = requests.post(f"{API}/personalized-risk-check", json=payload)

            if response.status_code != 200:
                st.error(response.text)
            else:
                result = response.json()
                m1, m2 = st.columns(2)
                m1.metric("Risk Score", result["risk_score"])
                m2.metric("Risk Level", result["risk_level"])

                st.subheader("Why this score?")
                for reason in result.get("reasons", []):
                    st.write(f"- {reason}")

                st.subheader("Profile Comparison")
                st.json(result.get("comparison", {}))

        except Exception as e:
            st.error(f"Risk check failed: {e}")


# ------------------------------------------------
# Fraud Detection
# ------------------------------------------------

elif page == "Fraud Detection":

    st.header("Fraud Risk Prediction")

    col1, col2, col3 = st.columns(3)

    with col1:
        user_id = st.text_input("User ID")

    with col2:
        merchant = st.text_input("Merchant")

    with col3:
        amount = st.number_input("Amount", min_value=0.0)

    if st.button("Analyze Transaction"):

        payload = {
            "amount": amount,
            "device_score": 0.5,
            "location_score": 0.5,
            "velocity_score": 1,
            "sender": user_id,
            "receiver": merchant,
            "timestamp": str(datetime.now())
        }

        try:

            response = requests.post(f"{API}/predict", json=payload)

            if response.status_code != 200:
                st.error(response.text)

            else:

                result = response.json()

                col1, col2 = st.columns(2)

                with col1:
                    st.metric("Risk Score", result["risk_score"])

                with col2:
                    level = "HIGH" if result["risk"] == 1 else "LOW"
                    st.metric("Risk Level", level)

                st.success(f"Transaction ID: {result['transaction_id']}")

                personalized = result.get("personalized_assessment")
                if personalized:
                    st.subheader("Personalized Behaviour Check")
                    p1, p2 = st.columns(2)
                    p1.metric("Profile Risk Score", personalized["risk_score"])
                    p2.metric("Profile Risk Level", personalized["risk_level"])

                    for reason in personalized.get("reasons", []):
                        st.write(f"- {reason}")

        except Exception as e:

            st.error(f"Connection Error: {e}")


# ------------------------------------------------
# Fraud Network Graph
# ------------------------------------------------

elif page == "Fraud Network Graph":

    st.header("Fraud Network Graph")

    try:

        data = requests.get(f"{API}/fraud-graph").json()

        edges = data["edges"]

        G = nx.Graph()

        for edge in edges:

            user = edge.get("user")
            merchant = edge.get("merchant")

            if user and merchant:
                G.add_edge(user, merchant)

        fig, ax = plt.subplots()

        nx.draw(G, with_labels=True)

        st.pyplot(fig)

    except:
        st.error("Network data unavailable")


# ------------------------------------------------
# Fraud Rings
# ------------------------------------------------

elif page == "Fraud Rings":

    st.header("Detected Fraud Rings")

    try:

        data = requests.get(f"{API}/fraud-rings").json()

        rings = data["rings"]

        if len(rings) == 0:

            st.success("No Fraud Rings Detected")

        else:

            for r in rings:
                st.warning(f"User {r[0]} → Merchant {r[1]}")

    except:
        st.error("Fraud ring data unavailable")


# ------------------------------------------------
# Fraud Heatmap
# ------------------------------------------------

elif page == "Fraud Heatmap":

    st.header("Fraud Activity Heatmap")

    try:

        data = requests.get(f"{API}/heatmap").json()

        if "error" in data:
            st.warning(data["error"])

        else:

            df = pd.DataFrame(data)

            st.scatter_chart(df)

    except:
        st.error("Heatmap unavailable")


# ------------------------------------------------
# Explainability
# ------------------------------------------------

elif page == "Explainability":

    st.header("Model Explainability")

    tx_id = st.text_input("Transaction ID")

    if st.button("Explain Prediction"):

        try:

            data = requests.get(f"{API}/explain/{tx_id}").json()

            st.json(data)

        except:

            st.error("Explainability service unavailable")


# ------------------------------------------------
# Fraud Alerts
# ------------------------------------------------

elif page == "Fraud Alerts":

    st.header("Fraud Alerts")

    try:

        tx = requests.get(f"{API}/transactions").json()

        alerts = [t for t in tx if t["risk"] == 1]

        if len(alerts) == 0:

            st.success("No alerts")

        else:

            for a in alerts:
                st.error(f"Fraud Transaction: {a['transaction_id']}  | Risk Score: {a['risk_score']}")

    except:

        st.error("Alert system unavailable")


# ------------------------------------------------
# System Monitor
# ------------------------------------------------

elif page == "System Monitor":

    st.header("System Health")

    try:

        data = requests.get(f"{API}/transactions").json()

        df = pd.DataFrame(data)

        st.dataframe(df)

    except:

        st.error("Backend not responding")
