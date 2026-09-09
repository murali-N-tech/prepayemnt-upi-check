import express, { type NextFunction, type Request, type Response } from "express";
import path from "path";
import fs from "fs";
import crypto from "crypto";
import multer from "multer";
import { createServer as createViteServer } from "vite";

// Load .env (Node >= 20.12). Real environment variables still win.
try {
  process.loadEnvFile();
} catch {
  // No .env file - fall back to the ambient environment.
}

const JWT_SECRET = process.env.JWT_SECRET;
if (!JWT_SECRET) {
  console.error(
    "Missing JWT_SECRET. Copy .env.example to .env and set it:\n" +
      '  node -e "console.log(require(\'crypto\').randomBytes(32).toString(\'hex\'))"'
  );
  process.exit(1);
}

const app = express();
const PORT = Number(process.env.PORT ?? 3001);

app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Configure Multer for uploaded files.
// One upload previously inserted 250,000 rows and grew the database to 147 MB.
const MAX_STATEMENT_BYTES = 10 * 1024 * 1024;
const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: MAX_STATEMENT_BYTES, files: 1 },
});

// File Paths for local databases
const DATA_DIR = path.join(process.cwd(), "data");

// Ensure data directory exists
if (!fs.existsSync(DATA_DIR)) {
  fs.mkdirSync(DATA_DIR, { recursive: true });
}

// -----------------------------------------------------------------------------
// AUTH SYSTEM
// -----------------------------------------------------------------------------

interface AuthUser {
  user_id: string;
  username: string;
}

interface AuthedRequest extends Request {
  authUser: AuthUser;
}

// --- HS256 JWT verification -------------------------------------------------
// Tokens are ISSUED by the Python service, which owns the single users table.
// Express only verifies them, using the same JWT_SECRET. Keeping two user
// stores meant an account created in one could not sign in to the other, and a
// profile built through one backend was invisible to the other.

function verifyToken(token: string): AuthUser | null {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  const [header, payload, signature] = parts;

  const expected = crypto
    .createHmac("sha256", JWT_SECRET as string)
    .update(`${header}.${payload}`)
    .digest("base64url");

  const given = Buffer.from(signature);
  const want = Buffer.from(expected);
  if (given.length !== want.length || !crypto.timingSafeEqual(given, want)) {
    return null;
  }

  try {
    const claims = JSON.parse(Buffer.from(payload, "base64url").toString("utf-8"));
    if (typeof claims.exp !== "number" || claims.exp * 1000 <= Date.now()) return null;
    if (typeof claims.sub !== "string" || !claims.sub) return null;
    return { user_id: claims.sub, username: claims.username ?? claims.sub };
  } catch {
    return null;
  }
}

function resolveTokenToUser(authHeader: string | undefined): AuthUser | null {
  if (!authHeader) return null;
  const token = authHeader.replace(/^Bearer\s+/i, "").trim();
  if (!token) return null;
  return verifyToken(token);
}

/** Rejects the request unless it carries a valid token. Populates req.authUser. */
function requireAuth(req: Request, res: Response, next: NextFunction) {
  const user = resolveTokenToUser(req.headers.authorization);
  if (!user) {
    return res.status(401).json({ detail: "Unauthorized" });
  }
  (req as AuthedRequest).authUser = user;
  next();
}

/** The authenticated user for a route mounted behind requireAuth. */
function currentUser(req: Request): AuthUser {
  return (req as AuthedRequest).authUser;
}


// -----------------------------------------------------------------------------
// IN-MEMORY & FILE STORAGE OPERATIONS
// -----------------------------------------------------------------------------

// Transactions are written by the Python service, which owns /predict. Two
// processes appending to the same CSV is how rows get lost.

// -----------------------------------------------------------------------------
// PYTHON BACKEND PROXY
// -----------------------------------------------------------------------------
// The payee intelligence (VPA analysis, QR parsing, reputation) lives in the
// Python service so there is exactly one implementation of it. Express forwards
// rather than re-implementing, the same way PDF parsing is already forwarded.

const PYTHON_BACKEND = process.env.PYTHON_BACKEND_URL ?? "http://127.0.0.1:8000";

async function forwardJson(
  path: string,
  body: unknown,
  authorization: string | undefined,
  method: "POST" | "GET" = "POST"
): Promise<{ status: number; body: any }> {
  const payload = JSON.stringify(body ?? {});
  const target = new URL(path, PYTHON_BACKEND);
  const http = await import("http");

  return new Promise((resolve, reject) => {
    const req = http.request(
      {
        hostname: target.hostname,
        port: target.port || 80,
        path: target.pathname,
        method,
        headers: {
          ...(method === "POST"
            ? {
                "Content-Type": "application/json",
                "Content-Length": Buffer.byteLength(payload),
              }
            : {}),
          ...(authorization ? { Authorization: authorization } : {}),
        },
      },
      (res) => {
        let raw = "";
        res.on("data", (c) => (raw += c));
        res.on("end", () => {
          try {
            resolve({ status: res.statusCode ?? 500, body: JSON.parse(raw) });
          } catch {
            resolve({
              status: 502,
              body: { detail: `Backend returned invalid JSON: ${raw.slice(0, 200)}` },
            });
          }
        });
      }
    );
    req.on("error", (err) => reject(err));
    if (method === "POST") req.write(payload);
    req.end();
  });
}

/** Forwards an uploaded file to the Python service. */
async function proxyUpload(req: Request, res: Response, path: string) {
  const file = (req as Request & { file?: Express.Multer.File }).file;
  if (!file) {
    return res.status(400).json({ detail: "No file uploaded" });
  }
  try {
    const FormData = (await import("form-data")).default;
    const form = new FormData();
    form.append("retain_source", String(req.body?.retain_source === "true"));
    form.append("file", file.buffer, {
      filename: file.originalname || "statement",
      contentType: file.mimetype || "application/octet-stream",
    });

    const target = new URL(path, PYTHON_BACKEND);
    const http = await import("http");
    const upstream = await new Promise<{ status: number; body: any }>((resolve, reject) => {
      const r = http.request(
        {
          hostname: target.hostname,
          port: target.port || 80,
          path: target.pathname,
          method: "POST",
          headers: {
            ...form.getHeaders(),
            ...(req.headers.authorization ? { Authorization: req.headers.authorization } : {}),
          },
        },
        (up) => {
          let raw = "";
          up.on("data", (c) => (raw += c));
          up.on("end", () => {
            try {
              resolve({ status: up.statusCode ?? 500, body: JSON.parse(raw) });
            } catch {
              resolve({ status: 502, body: { detail: `Bad JSON from backend: ${raw.slice(0, 200)}` } });
            }
          });
        }
      );
      r.on("error", reject);
      form.pipe(r);
    });
    res.status(upstream.status).json(upstream.body);
  } catch (err: any) {
    res.status(503).json({
      detail:
        `The statement parser is not running. Start it with "python backend/main.py" ` +
        `and try again. (${err.message})`,
    });
  }
}

/** Forwards a request, turning an unreachable backend into a clear message. */
async function proxyToPython(
  req: Request,
  res: Response,
  path: string,
  method: "POST" | "GET" = "POST"
) {
  try {
    const { status, body } = await forwardJson(
      path,
      method === "POST" ? req.body : null,
      req.headers.authorization,
      method
    );
    res.status(status).json(body);
  } catch (err: any) {
    res.status(503).json({
      detail:
        `The payee intelligence service is not running. Start it with ` +
        `"python backend/main.py" and try again. (${err.message})`,
    });
  }
}

// -----------------------------------------------------------------------------
// CORE BUSINESS LOGIC & COMPATIBILITY ENDPOINTS
// -----------------------------------------------------------------------------

// Home & Health
app.get(["/", "/api"], (_req, res) => {
  res.json({ message: "Edge AI UPI Behaviour Risk System Running (Node.js)" });
});

app.get(["/health", "/api/health"], (_req, res) => {
  res.json({ status: "ok" });
});

// GET Transactions List

// POST Analyze / Predict Transaction
// Scoring lives in the Python service, which owns the trained model. Express
// used to run its own hardcoded rule ladder here, so the same transaction
// scored differently depending on which backend answered.
// Auth is issued by the Python service, which owns the single users table.
app.post(["/auth/register", "/api/auth/register"], (req, res) =>
  proxyToPython(req, res, "/auth/register")
);
app.post(["/auth/login", "/api/auth/login"], (req, res) =>
  proxyToPython(req, res, "/auth/login")
);

app.get(["/transactions", "/api/transactions"], requireAuth, (req, res) =>
  proxyToPython(req, res, "/transactions", "GET")
);

app.get(["/statement-transactions", "/api/statement-transactions"], requireAuth, (req, res) => {
  const q = new URLSearchParams(req.query as Record<string, string>).toString();
  return proxyToPython(req, res, `/statement-transactions${q ? `?${q}` : ""}`, "GET");
});

app.get(["/profiles/me", "/api/profiles/me"], requireAuth, (req, res) =>
  proxyToPython(req, res, "/profiles/me", "GET")
);

app.post(["/personalized-risk-check", "/api/personalized-risk-check"], requireAuth, (req, res) =>
  proxyToPython(req, res, "/personalized-risk-check")
);

app.post(["/predict", "/api/predict"], requireAuth, (req, res) => {
  // The payer is whoever holds the token; never trust a client-supplied id.
  req.body = { ...(req.body ?? {}), sender: currentUser(req).user_id };
  return proxyToPython(req, res, "/predict");
});

// GET Heatmap coords
app.get(["/heatmap", "/api/heatmap"], requireAuth, (req, res) =>
  proxyToPython(req, res, "/heatmap", "GET")
);

// GET SHAP Explainer
app.get(["/explain/:tx_id", "/api/explain/:tx_id"], requireAuth, (req, res) =>
  // Real SHAP values against a real background distribution, rather than the
  // weights that used to be reverse-engineered from the score here.
  proxyToPython(req, res, `/explain/${encodeURIComponent(req.params.tx_id)}`, "GET")
);

// GET Fraud Graph Edges
app.get(["/fraud-graph", "/api/fraud-graph"], requireAuth, (req, res) =>
  proxyToPython(req, res, "/fraud-graph", "GET")
);

// GET Fraud Rings
// Graph analysis lives in the Python service so there is one implementation.
// The versions that used to be here walked every node and reported anything
// with three or more neighbours, which on real data returns popular merchants.
app.get(["/fraud-rings", "/api/fraud-rings"], requireAuth, (req, res) =>
  proxyToPython(req, res, "/fraud-rings", "GET")
);

// GET Temporal Patterns (count fraud transactions by hour)
app.get(["/temporal-patterns", "/api/temporal-patterns"], requireAuth, (req, res) =>
  proxyToPython(req, res, "/temporal-patterns", "GET")
);

// GET Behavioral Biometrics
app.get(["/behavior/:tx_id", "/api/behavior/:tx_id"], requireAuth, (req, res) =>
  proxyToPython(req, res, `/behavior/${encodeURIComponent(req.params.tx_id)}`, "GET")
);

// GET Model Drift status
app.get(["/model-drift", "/api/model-drift"], requireAuth, (req, res) =>
  proxyToPython(req, res, "/model-drift", "GET")
);

// GET GNN Fraud Detection (suspicious nodes with degree >= 3)
app.get(["/gnn-fraud-detection", "/api/gnn-fraud-detection"], requireAuth, (req, res) =>
  proxyToPython(req, res, "/gnn-fraud-detection", "GET")
);

// GET Profile by user_id



// POST Upload Statement (PDF/CSV)
// Statement parsing lives in the Python service, which has pdfplumber and the
// four extraction strategies. Express used to parse CSV itself and forward
// only PDFs, which is how the two backends ended up with different profiles
// for the same user.
app.post(
  ["/statement/upload", "/api/statement/upload"],
  requireAuth,
  upload.single("file"),
  (req, res) => proxyUpload(req, res, "/statement/upload")
);

app.post(["/payee/check", "/api/payee/check"], requireAuth, (req, res) =>
  proxyToPython(req, res, "/payee/check")
);

app.post(["/payee/report", "/api/payee/report"], requireAuth, (req, res) =>
  proxyToPython(req, res, "/payee/report")
);

app.post(["/payee/confirm", "/api/payee/confirm"], requireAuth, (req, res) =>
  proxyToPython(req, res, "/payee/confirm")
);

// Unknown /api/* paths must fail as JSON. Without this they fall through to
// the SPA fallback below, which answers an API call with HTML (or hangs while
// the dev server tries to resolve the path as a module).
app.use(["/api", "/api/*"], (req, res) => {
  // Name the route that missed. A bare "Unknown API endpoint" cannot be told
  // apart from a stale server process that never registered the route at all.
  res.status(404).json({
    detail: `Unknown API endpoint: ${req.method} ${req.originalUrl}. If this route ` +
      `exists in server.ts, the running server is older than the file - restart it.`,
  });
});

async function startServer() {
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa"
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*", (_req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  app.listen(PORT, "0.0.0.0", async () => {
    console.log(`Server running on http://localhost:${PORT}`);

    // The payee check is proxied, so its usefulness depends on a second
    // process. Say so at startup rather than at the first failed request.
    try {
      const { status } = await forwardJson("/health", null, undefined, "GET");
      console.log(
        status === 200
          ? `Payee intelligence service reachable at ${PYTHON_BACKEND}`
          : `Payee intelligence service at ${PYTHON_BACKEND} answered ${status}`
      );
    } catch {
      console.warn(
        `Payee intelligence service NOT reachable at ${PYTHON_BACKEND}.\n` +
          `  "Check a Payee" and PDF upload will fail until you run:  python backend/main.py`
      );
    }
  });
}

startServer();
