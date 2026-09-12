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
    # Some rows carry a timezone offset and some do not, and pandas returns an
    # object column for that mixture, which breaks .dt. utc=True fixed the dtype
    # but introduced a worse bug: it CONVERTS an offset-bearing value, so
    # "2026-06-01T02:30:00+05:30" was binned at hour 21 while the naive row
    # beside it stayed at hour 2. The chart then mixed IST hours and UTC hours
    # in the same 24 buckets.
    #
    # This is an hour-of-day chart, so the hour wanted is the one on the clock
    # the payer was looking at - which is exactly what the string already says.
    # Dropping the offset before parsing keeps that hour and gives a uniform
    # naive dtype at the same time.
    naive = (
        frame["timestamp"]
        .astype("string")
        .str.replace(r"(?:Z|[+-]\d{2}:?\d{2})\s*$", "", regex=True)
    )
    frame["timestamp"] = pd.to_datetime(naive, errors="coerce", format="mixed")
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
