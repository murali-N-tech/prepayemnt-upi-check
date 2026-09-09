# Security notes

## A database password was committed and pushed

`backend/app/core/database.py` contained a Postgres password inline. It was
moved to an environment variable, but it remains in the git history and that
history was pushed to `origin/main`.

**Rotating the password is the fix.** Rewriting history is optional cleanup and
does not undo the exposure:

- If the GitHub repository is or ever was public, treat the password as known.
- Even after a force-push, GitHub keeps unreferenced objects reachable by SHA
  for a period, and forks and clones keep their own copies.
- Anyone who cloned before the rewrite still has it.

### 1. Rotate (do this first)

```sql
ALTER USER postgres WITH PASSWORD 'a-new-strong-password';
```

Put the new value in `.env` as `PGPASSWORD`. `.env` is gitignored, and
`backend/app/core/config.py` fails loudly at import if the variable is missing,
so a missing secret is a startup error rather than a silent fallback.

### 2. Optionally scrub the history

Only worth doing if the repository is private and you know who has clones. It
rewrites every commit SHA, so anyone else working on it must re-clone.

```bash
pip install git-filter-repo

git clone --mirror https://github.com/murali-N-tech/pay.git pay-mirror
cd pay-mirror
git filter-repo --path backend/app/core/database.py --invert-paths
git push --force --all
git push --force --tags
```

Tell every collaborator to re-clone. Do not merge an old clone back in
afterwards - it reintroduces the old history.

### 3. Prevention

`scripts/check_secrets.py` scans tracked files for hardcoded passwords,
connection strings, private keys and API keys. CI runs it on every push, so a
credential fails the build rather than reaching the history.

```bash
python scripts/check_secrets.py
```

To catch it even earlier, run it before each commit:

```bash
printf '#!/bin/sh\npython scripts/check_secrets.py\n' > .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

## Where secrets live now

| variable | used by | required |
|---|---|---|
| `JWT_SECRET` | token signing and verification, both backends | yes |
| `PGPASSWORD` | `backend/api.py` only | only if you run it |
| `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER` | same | defaults provided |

Both backends sign and verify with the same `JWT_SECRET`, which is what lets
Express verify a token that FastAPI issued. Changing it signs everyone out.
