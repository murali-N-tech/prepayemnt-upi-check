from __future__ import annotations
import os
import json
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

class FeatureStore:
    def __init__(self):
        self.path = Path("data/feature_store")
        self.path.mkdir(parents=True, exist_ok=True)

    def save(self, df: pd.DataFrame, name: str) -> None:
        file_path = self.path / f"{name}.parquet"
        df.to_parquet(file_path)

    def load(self, name: str) -> pd.DataFrame | None:
        file_path = self.path / f"{name}.parquet"
        if file_path.exists():
            return pd.read_parquet(file_path)
        return None

    def save_user_features(self, user_id: str, features: dict) -> None:
        cache_file = self.path / f"user_{user_id}_features.json"

        # Convert pandas types or floats to primitives
        clean_features = {}
        for k, v in features.items():
            if pd.isna(v):
                clean_features[k] = None
            elif isinstance(v, (np.integer, int)):
                clean_features[k] = int(v)
            elif isinstance(v, (np.floating, float)):
                clean_features[k] = float(v)
            else:
                clean_features[k] = v

        payload = {
            "timestamp": datetime.utcnow().isoformat(),
            "features": clean_features
        }
        with open(cache_file, "w") as f:
            json.dump(payload, f)

    def load_user_features(self, user_id: str) -> dict | None:
        cache_file = self.path / f"user_{user_id}_features.json"
        if not cache_file.exists():
            return None

        try:
            with open(cache_file, "r") as f:
                payload = json.load(f)

            # Check 24 hour TTL
            cached_time = datetime.fromisoformat(payload["timestamp"])
            if datetime.utcnow() - cached_time > timedelta(hours=24):
                return None

            return payload["features"]
        except Exception:
            return None

    def invalidate(self, user_id: str) -> None:
        cache_file = self.path / f"user_{user_id}_features.json"
        if cache_file.exists():
            try:
                cache_file.unlink()
            except OSError:
                pass