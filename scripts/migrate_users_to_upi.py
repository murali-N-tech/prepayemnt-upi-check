"""Rename existing accounts to the UPI ID that identifies them.

Accounts used to be identified by an arbitrary username. They are now
identified by the user's own UPI ID, which is what lets a statement line up
with the payee graph. Existing accounts need their identifier changed, and
only the account holder knows which address is theirs - so this takes explicit
mappings rather than guessing.

    python scripts/migrate_users_to_upi.py --list
    python scripts/migrate_users_to_upi.py --map murali=murali@okaxis --dry-run
    python scripts/migrate_users_to_upi.py --map murali=murali@okaxis
    python scripts/migrate_users_to_upi.py --delete demo_user --delete yash

A username that is a 10-digit phone number can be mapped automatically with
--auto-phone, which produces <number>@upi. Check that is actually the address
the person pays from before using it.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.services.profile_store import _get_connection  # noqa: E402
from backend.app.services.upi_verify import verify_vpa  # noqa: E402

PHONE = re.compile(r"^[6-9]\d{9}$")


def show(conn) -> None:
    print(f"\n  {'username':28} {'upi_id':28} {'id':14} {'statements':>10}")
    for r in conn.execute("SELECT id, username, upi_id FROM users ORDER BY username"):
        n = conn.execute(
            "SELECT COUNT(*) FROM statement_transactions WHERE user_id = ?", (r["id"],)
        ).fetchone()[0]
        looks_upi = "@" in (r["username"] or "")
        flag = "" if looks_upi else "   <- not a UPI ID"
        print(f"  {r['username']:28} {str(r['upi_id'] or '-'):28} {r['id']:14} {n:>10}{flag}")
    print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="show accounts and exit")
    ap.add_argument("--map", action="append", default=[], metavar="OLD=UPI_ID")
    ap.add_argument("--delete", action="append", default=[], metavar="USERNAME")
    ap.add_argument("--auto-phone", action="store_true",
                    help="map a 10-digit phone-number username to <number>@upi")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = _get_connection()
    try:
        if args.list or not (args.map or args.delete or args.auto_phone):
            show(conn)
            if not args.list:
                print("  Nothing to do. Pass --map OLD=UPI_ID, --delete USERNAME, "
                      "or --auto-phone.\n")
            return 0

        pairs: list[tuple[str, str]] = []
        for entry in args.map:
            if "=" not in entry:
                print(f"  skipping {entry!r}: expected OLD=UPI_ID")
                continue
            old, new = entry.split("=", 1)
            pairs.append((old.strip(), new.strip().lower()))

        if args.auto_phone:
            for r in conn.execute("SELECT username FROM users"):
                name = r["username"]
                if PHONE.match(name or ""):
                    pairs.append((name, f"{name}@upi"))

        conn.execute("BEGIN")
        for old, new in pairs:
            row = conn.execute("SELECT id FROM users WHERE username = ?", (old,)).fetchone()
            if not row:
                print(f"  {old:24} not found, skipping")
                continue
            check = verify_vpa(new)
            if check.status in {"malformed", "not_found"}:
                print(f"  {old:24} -> {new:26} REJECTED: {check.detail}")
                continue
            taken = conn.execute(
                "SELECT 1 FROM users WHERE username = ? AND id != ?", (new, row["id"])
            ).fetchone()
            if taken:
                print(f"  {old:24} -> {new:26} REJECTED: already registered")
                continue
            conn.execute(
                "UPDATE users SET username = ?, upi_id = ?, upi_verified = ? WHERE id = ?",
                (new, new, 1 if (check.ok and check.checked_with_provider) else 0, row["id"]),
            )
            state = "verified" if check.ok and check.checked_with_provider else "format checked"
            print(f"  {old:24} -> {new:26} ok ({state})")

        for name in args.delete:
            row = conn.execute("SELECT id FROM users WHERE username = ?", (name,)).fetchone()
            if not row:
                print(f"  {name:24} not found, skipping")
                continue
            n = conn.execute(
                "SELECT COUNT(*) FROM statement_transactions WHERE user_id = ?", (row["id"],)
            ).fetchone()[0]
            conn.execute("DELETE FROM users WHERE id = ?", (row["id"],))
            print(f"  {name:24} deleted (its {n} statement rows are left in place)")

        if args.dry_run:
            conn.rollback()
            print("\n  (dry run - nothing changed)")
        else:
            conn.commit()
            show(conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
