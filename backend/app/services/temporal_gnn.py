"""Flagged transactions by hour of day.

Timestamps in the store come from several sources - statement parsing, live
scoring, migrated rows - so they are not all in one format. pandas infers a
format from the first value and then raises on the first row that differs,
which is what took this endpoint down after the migration. Parsing is
therefore explicitly format-agnostic, and unparseable rows are dropped rather
than failing the whole request.
"""

from __future__ import annotations

import pandas as pd


def temporal_patterns(df: pd.DataFrame) -> dict[str, int]:
    if df is None or df.empty or "timestamp" not in df.columns:
        return {}

    frame = df.copy()
    # Some rows carry a timezone and some do not. Without utc=True pandas
    # returns an object column for that mixture and .dt stops working, so the
    # parse is normalised to UTC. Naive values keep their clock hour, which is
    # what an hour-of-day chart is reading.
    frame["timestamp"] = pd.to_datetime(
        frame["timestamp"], errors="coerce", format="mixed", utc=True
    )
    frame = frame.loc[frame["timestamp"].notna()]
    if frame.empty:
        return {}

    if "risk" in frame.columns:
        frame["risk"] = pd.to_numeric(frame["risk"], errors="coerce").fillna(0)
    else:
        frame["risk"] = 0

    by_hour = frame.groupby(frame["timestamp"].dt.hour)["risk"].sum()

    # Every hour present, so the caller can chart a full day without filling
    # gaps itself. Keys are strings because JSON object keys are strings.
    return {str(hour): int(by_hour.get(hour, 0)) for hour in range(24)}
