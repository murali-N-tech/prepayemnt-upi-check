import psycopg2
from psycopg2.extras import RealDictCursor  # noqa: F401  (used by callers)

from backend.app.core.config import get, require


def get_connection():
    """Open a Postgres connection using credentials from the environment."""
    return psycopg2.connect(
        host=get("PGHOST", "localhost"),
        port=int(get("PGPORT", "5432")),
        database=get("PGDATABASE", "edge_upi_risk"),
        user=get("PGUSER", "postgres"),
        password=require("PGPASSWORD"),
    )
