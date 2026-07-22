import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import IsolationForest
import os

os.makedirs("models", exist_ok=True)

# Generate dummy data
X = np.random.rand(100, 5)
y = np.random.randint(0, 2, 100)

log_model = LogisticRegression()
log_model.fit(X, y)

iso_features = X[:, :3]
iso_model = IsolationForest()
iso_model.fit(iso_features)

joblib.dump(log_model, "models/logistic_model.pkl")
joblib.dump(iso_model, "models/isolation_forest.pkl")

print("Models generated successfully.")
