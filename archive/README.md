# archive/

Earlier exploratory modules, moved out of `backend/` because nothing in the
running system imports them.

They were counted in the audit as ~40 near-empty files spread across
`advanced_ai/`, `gnn/`, `knowledge_graph/`, `streaming/`, `stress_testing/`,
`monitoring/`, `pipeline/` and `realtime/` — most 200–900 bytes, several
implementing the same idea under different names (`ultra_risk_engine`,
`hybrid_risk_engine`, `advanced_risk_engine`, `fraud_reasoning_engine`). A
reviewer opening `backend/` read them as padding, which undercut the parts
that are real.

Nothing here runs, is imported, or is tested. It is kept rather than deleted
because some of it sketches work that is genuinely next — Kafka streaming, a
retraining pipeline, drift monitoring, a knowledge graph. If one of them gets
built for real, it should come back as a working module with tests, not as
the stub that is here.

What replaced the ones that mattered:

| archived | replaced by |
|---|---|
| `advanced_ai/*_risk_engine.py` | `backend/app/services/payee_check.py` |
| `gnn/temporal_gnn_model.py`, `graph/gnn_fraud_detector.py` | `backend/app/services/fraud_graph.py` |
| `explainability/shap_explainer.py`, `app/services/shap_service.py` | real SHAP in `backend/main.py` `/explain` |
| `models/train_model.py` | `backend/train_model.py` |
| `monitoring/model_monitor.py` | `models/metrics.json` from the training run |
| `app/services/db_service.py`, `postgres_service.py` | `backend/app/services/profile_store.py` |
