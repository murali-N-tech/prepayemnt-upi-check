import express from "express";
import path from "path";
import fs from "fs";
import crypto from "crypto";
import multer from "multer";
import { createServer as createViteServer } from "vite";
import { createRequire } from "module";

const require = createRequire(import.meta.url);
const PDFParser = require("pdf2json");

// Helper: extract all text from a PDF buffer using pdf2json
function extractPdfText(buffer: Buffer): Promise<string> {
  return new Promise((resolve, reject) => {
    const parser = new PDFParser(null, true);
    parser.on("pdfParser_dataReady", (pdfData: any) => {
      try {
        const pages = pdfData?.Pages || [];
        const allText: string[] = [];
        for (const page of pages) {
          const texts = page.Texts || [];
          for (const t of texts) {
            const runs = t.R || [];
            for (const r of runs) {
              allText.push(decodeURIComponent(r.T || ""));
            }
          }
        }
        resolve(allText.join(" "));
      } catch (e: any) {
        reject(e);
      }
    });
    parser.on("pdfParser_dataError", (err: any) => {
      reject(new Error(err?.parserError || "PDF parsing failed"));
    });
    parser.parseBuffer(buffer);
  });
}

const app = express();
const PORT = 3001;

app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Configure Multer for uploaded files
const upload = multer({ storage: multer.memoryStorage() });

// File Paths for local databases
const DB_FILE = path.join(process.cwd(), "transactions.csv");
const DATA_DIR = path.join(process.cwd(), "data");
const PROFILES_FILE = path.join(DATA_DIR, "behavior_profiles.json");
const STATEMENT_TXS_FILE = path.join(DATA_DIR, "statement_transactions.json");
const USERS_FILE = path.join(DATA_DIR, "users.json");

// Ensure data directory exists
if (!fs.existsSync(DATA_DIR)) {
  fs.mkdirSync(DATA_DIR, { recursive: true });
}

// -----------------------------------------------------------------------------
// AUTH SYSTEM
// -----------------------------------------------------------------------------

interface StoredUser {
  user_id: string;
  username: string;
  password: string;
}

interface TokenMapping {
  token: string;
  user_id: string;
  username: string;
}

// In-memory token store (persisted tokens are regenerated on login)
const activeTokens: TokenMapping[] = [];

function readUsers(): StoredUser[] {
  if (!fs.existsSync(USERS_FILE)) return [];
  try {
    return JSON.parse(fs.readFileSync(USERS_FILE, "utf-8"));
  } catch {
    return [];
  }
}

function saveUsers(users: StoredUser[]) {
  fs.writeFileSync(USERS_FILE, JSON.stringify(users, null, 2), "utf-8");
}

function generateToken(): string {
  return "tok_" + crypto.randomBytes(24).toString("hex");
}

function resolveTokenToUser(authHeader: string | undefined): TokenMapping | null {
  if (!authHeader) return null;
  const token = authHeader.replace(/^Bearer\s+/i, "").trim();
  return activeTokens.find(t => t.token === token) || null;
}

// POST /api/auth/register
app.post(["/auth/register", "/api/auth/register"], (req, res) => {
  const { username, password } = req.body;
  if (!username || !password) {
    return res.status(400).json({ detail: "Username and password are required" });
  }

  const users = readUsers();
  const existing = users.find(u => u.username.toLowerCase() === username.toLowerCase());
  if (existing) {
    return res.status(409).json({ detail: "Username already exists" });
  }

  const user_id = "user_" + crypto.randomBytes(8).toString("hex");
  const newUser: StoredUser = { user_id, username, password };
  users.push(newUser);
  saveUsers(users);

  const token = generateToken();
  activeTokens.push({ token, user_id, username });

  res.json({ token, user_id, username });
});

// POST /api/auth/login
app.post(["/auth/login", "/api/auth/login"], (req, res) => {
  const { username, password } = req.body;
  if (!username || !password) {
    return res.status(400).json({ detail: "Username and password are required" });
  }

  const users = readUsers();
  const user = users.find(
    u => u.username.toLowerCase() === username.toLowerCase() && u.password === password
  );

  if (!user) {
    return res.status(401).json({ detail: "Invalid username or password" });
  }

  const token = generateToken();
  activeTokens.push({ token, user_id: user.user_id, username: user.username });

  res.json({ token, user_id: user.user_id, username: user.username });
});

// -----------------------------------------------------------------------------
// IN-MEMORY & FILE STORAGE OPERATIONS
// -----------------------------------------------------------------------------

interface TransactionRecord {
  transaction_id: string;
  amount: number;
  device_score: number;
  location_score: number;
  velocity_score: number;
  sender: string;
  receiver: string;
  timestamp: string;
  risk: number;
  risk_score: number;
}

interface StatementTransaction {
  statement_id: string;
  user_id: string;
  timestamp: string;
  amount: number;
  merchant: string;
  upi_id?: string;
  status: string;
  reference_number?: string;
  source_type: string;
  raw_line: string;
  created_at: string;
}

interface BehaviorProfile {
  user_id: string;
  transaction_count: number;
  avg_amount: number;
  max_amount: number;
  min_amount: number;
  most_active_hour: number | null;
  night_transactions: number;
  weekend_transactions: number;
  favorite_merchants: string[];
  average_daily_transactions: number;
  failed_transactions: number;
  known_upi_ids: string[];
  merchant_frequency: Record<string, number>;
  hourly_distribution: Record<string, number>;
  monthly_totals: Record<string, number>;
  source_type: string;
  updated_at: string;
}

// Helper to read and parse CSV Transactions
function readCsvTransactions(): TransactionRecord[] {
  if (!fs.existsSync(DB_FILE)) {
    return [];
  }
  try {
    const data = fs.readFileSync(DB_FILE, "utf-8");
    const lines = data.split(/\r?\n/);
    if (lines.length <= 1) return [];

    const headers = lines[0].split(",").map(h => h.trim());
    const records: TransactionRecord[] = [];

    for (let i = 1; i < lines.length; i++) {
      if (!lines[i].trim()) continue;
      // Handle simple CSV splitting (assuming no embedded commas for this dataset)
      const values = lines[i].split(",").map(v => v.trim());
      if (values.length < headers.length) continue;

      const rec: any = {};
      headers.forEach((header, idx) => {
        const val = values[idx];
        if (header === "amount" || header === "device_score" || header === "location_score" || header === "velocity_score" || header === "risk" || header === "risk_score") {
          rec[header] = parseFloat(val) || 0;
        } else {
          rec[header] = val;
        }
      });
      records.push(rec as TransactionRecord);
    }
    return records;
  } catch (err) {
    console.error("Error reading transactions CSV:", err);
    return [];
  }
}

// Helper to write CSV Transactions
function writeCsvTransaction(tx: TransactionRecord) {
  try {
    const fileExists = fs.existsSync(DB_FILE);
    const headers = ["transaction_id", "amount", "device_score", "location_score", "velocity_score", "sender", "receiver", "timestamp", "risk", "risk_score"];
    let csvLine = `${tx.transaction_id},${tx.amount},${tx.device_score},${tx.location_score},${tx.velocity_score},${tx.sender},${tx.receiver},${tx.timestamp},${tx.risk},${tx.risk_score}\n`;
    
    if (!fileExists) {
      const headerLine = headers.join(",") + "\n";
      fs.writeFileSync(DB_FILE, headerLine + csvLine, "utf-8");
    } else {
      fs.appendFileSync(DB_FILE, csvLine, "utf-8");
    }
  } catch (err) {
    console.error("Error writing transaction to CSV:", err);
  }
}

// Load and save statement transactions JSON
function readStatementTransactions(): StatementTransaction[] {
  if (!fs.existsSync(STATEMENT_TXS_FILE)) {
    return [];
  }
  try {
    return JSON.parse(fs.readFileSync(STATEMENT_TXS_FILE, "utf-8"));
  } catch {
    return [];
  }
}

function saveStatementTransactions(txs: StatementTransaction[]) {
  try {
    const existing = readStatementTransactions();
    const combined = [...existing, ...txs];
    fs.writeFileSync(STATEMENT_TXS_FILE, JSON.stringify(combined, null, 2), "utf-8");
  } catch (err) {
    console.error("Error saving statement transactions:", err);
  }
}

// Load and save profiles JSON
function readBehaviorProfiles(): Record<string, BehaviorProfile> {
  if (!fs.existsSync(PROFILES_FILE)) {
    return {};
  }
  try {
    return JSON.parse(fs.readFileSync(PROFILES_FILE, "utf-8"));
  } catch {
    return {};
  }
}

function saveBehaviorProfile(userId: string, profile: BehaviorProfile) {
  try {
    const profiles = readBehaviorProfiles();
    profiles[userId] = profile;
    fs.writeFileSync(PROFILES_FILE, JSON.stringify(profiles, null, 2), "utf-8");
  } catch (err) {
    console.error("Error saving behavior profile:", err);
  }
}

// Graph connection storage
interface GraphEdge {
  user: string;
  merchant: string;
}
const graphEdges: GraphEdge[] = [];

// Populate graph connection cache from transactions.csv on start
function buildGraphCache() {
  const txs = readCsvTransactions();
  txs.forEach(t => {
    if (t.sender && t.receiver) {
      const exists = graphEdges.some(e => e.user === t.sender && e.merchant === t.receiver);
      if (!exists) {
        graphEdges.push({ user: t.sender, merchant: t.receiver });
      }
    }
  });
}
buildGraphCache();

// -----------------------------------------------------------------------------
// CORE BUSINESS LOGIC & COMPATIBILITY ENDPOINTS
// -----------------------------------------------------------------------------

// Home & Health
app.get(["/", "/api"], (req, res) => {
  res.json({ message: "Edge AI UPI Behaviour Risk System Running (Node.js)" });
});

app.get(["/health", "/api/health"], (req, res) => {
  res.json({ status: "ok" });
});

// GET Transactions List
app.get(["/transactions", "/api/transactions"], (req, res) => {
  const txs = readCsvTransactions();
  res.json(txs);
});

// POST Analyze / Predict Transaction
app.post(["/predict", "/api/predict"], (req, res) => {
  const { amount, device_score, location_score, velocity_score, sender, receiver, timestamp } = req.body;

  const currentAmount = parseFloat(amount) || 0;
  const devScore = parseFloat(device_score) || 0.5;
  const locScore = parseFloat(location_score) || 0.5;
  const velScore = parseFloat(velocity_score) || 1.0;
  const txSender = sender ? String(sender).trim() : "unknown_user";
  const txReceiver = receiver ? String(receiver).trim() : "unknown_merchant";
  const txTimestamp = timestamp || new Date().toISOString();

  let is_night = 0;
  try {
    const hour = new Date(txTimestamp).getHours();
    is_night = (hour < 6 || hour > 22) ? 1 : 0;
  } catch {
    is_night = 0;
  }

  // Calculate rolling statistics from tail 5
  const allTxs = readCsvTransactions();
  let rolling_avg_amount = currentAmount;
  let rolling_txn_count = 1;
  let time_gap = 100;

  if (allTxs.length > 0) {
    const last5 = allTxs.slice(-5);
    const sum = last5.reduce((acc, t) => acc + t.amount, 0);
    rolling_avg_amount = sum / last5.length;
    rolling_txn_count = last5.length;

    try {
      const lastTxTime = new Date(allTxs[allTxs.length - 1].timestamp).getTime();
      const currentTxTime = new Date(txTimestamp).getTime();
      time_gap = Math.max(1, Math.floor((currentTxTime - lastTxTime) / 1000));
    } catch {
      time_gap = 100;
    }
  }

  // Simulated machine-learning decision boundary resembling original Ensemble
  let base_prob = 0.15;
  if (currentAmount > 10000) base_prob += 0.12;
  if (currentAmount > 70000) base_prob += 0.35;
  if (velScore > 5) base_prob += 0.20;
  if (devScore > 0.7) base_prob += 0.08;
  if (locScore > 0.7) base_prob += 0.08;
  if (is_night === 1) base_prob += 0.10;

  let risk_score = Math.floor(Math.min(0.95, Math.max(0.05, base_prob)) * 100);
  let risk = (currentAmount > 70000 || velScore > 7 || risk_score >= 70) ? 1 : 0;

  const tx_id = `tx_${Math.random().toString(36).substr(2, 6)}`;
  const transactionData: TransactionRecord = {
    transaction_id: tx_id,
    amount: currentAmount,
    device_score: devScore,
    location_score: locScore,
    velocity_score: velScore,
    sender: txSender,
    receiver: txReceiver,
    timestamp: txTimestamp,
    risk,
    risk_score
  };

  // Persist
  writeCsvTransaction(transactionData);

  // Cache Edge
  const edgeExists = graphEdges.some(e => e.user === txSender && e.merchant === txReceiver);
  if (!edgeExists && txSender && txReceiver) {
    graphEdges.push({ user: txSender, merchant: txReceiver });
  }

  // Build personalized profile risk check if profile is available
  const profiles = readBehaviorProfiles();
  const profile = profiles[txSender];
  let personalized_assessment = null;

  if (profile) {
    const history = readStatementTransactions().filter(t => t.user_id === txSender);
    personalized_assessment = evaluatePersonalizedRiskLogic(profile, history, currentAmount, txReceiver, txTimestamp, null, null);
  }

  res.json({
    transaction_id: tx_id,
    risk,
    risk_score,
    personalized_assessment
  });
});

// GET Heatmap coords
app.get(["/heatmap", "/api/heatmap"], (req, res) => {
  const txs = readCsvTransactions();
  if (txs.length < 2) {
    return res.json({ error: "Not enough transactions" });
  }
  res.json({
    amount: txs.map(t => t.amount),
    risk: txs.map(t => t.risk)
  });
});

// GET SHAP Explainer
app.get(["/explain/:tx_id", "/api/explain/:tx_id"], (req, res) => {
  const { tx_id } = req.params;
  const txs = readCsvTransactions();
  const tx = txs.find(t => t.transaction_id === tx_id);

  if (!tx) {
    return res.status(404).json({ error: "Transaction Not Found" });
  }

  // Backwards compute relative shap weights based on values
  const amtWeight = tx.amount > 50000 ? 0.35 : tx.amount > 10000 ? 0.15 : 0.02;
  const nightWeight = (new Date(tx.timestamp).getHours() < 6 || new Date(tx.timestamp).getHours() >= 22) ? 0.12 : -0.05;
  const velWeight = tx.velocity_score > 5 ? 0.25 : -0.05;
  const locWeight = tx.location_score > 0.6 ? 0.10 : -0.02;
  const devWeight = tx.device_score > 0.6 ? 0.10 : -0.02;

  res.json({
    transaction_id: tx_id,
    features: ["amount", "is_night", "rolling_avg", "rolling_txn_count", "time_gap"],
    shap_values: [[
      amtWeight,
      nightWeight,
      velWeight * 0.5,
      locWeight * 0.5,
      devWeight * 0.5
    ]]
  });
});

// GET Fraud Graph Edges
app.get(["/fraud-graph", "/api/fraud-graph"], (req, res) => {
  res.json({ edges: graphEdges });
});

// GET Fraud Rings
app.get(["/fraud-rings", "/api/fraud-rings"], (req, res) => {
  // Group users connected to each merchant
  const merchantToUsers: Record<string, Set<string>> = {};
  graphEdges.forEach(edge => {
    if (!merchantToUsers[edge.merchant]) {
      merchantToUsers[edge.merchant] = new Set();
    }
    merchantToUsers[edge.merchant].add(edge.user);
  });

  const rings: any[] = [];
  Object.keys(merchantToUsers).forEach(merchant => {
    const users = Array.from(merchantToUsers[merchant]);
    if (users.length >= 3) {
      rings.push({
        merchant,
        users
      });
    }
  });

  res.json({ rings });
});

// GET Temporal Patterns (count fraud transactions by hour)
app.get(["/temporal-patterns", "/api/temporal-patterns"], (req, res) => {
  const txs = readCsvTransactions();
  const hourMap: Record<string, number> = {};
  for (let i = 0; i < 24; i++) {
    hourMap[i.toString()] = 0;
  }

  txs.forEach(t => {
    if (t.risk === 1) {
      try {
        const hour = new Date(t.timestamp).getHours();
        hourMap[hour.toString()] = (hourMap[hour.toString()] || 0) + 1;
      } catch {}
    }
  });

  res.json(hourMap);
});

// GET Behavioral Biometrics
app.get(["/behavior/:tx_id", "/api/behavior/:tx_id"], (req, res) => {
  const { tx_id } = req.params;
  const txs = readCsvTransactions();
  const tx = txs.find(t => t.transaction_id === tx_id);

  if (!tx) {
    return res.status(404).json({ error: "Transaction Not Found" });
  }

  const mean = (tx.velocity_score + tx.device_score) / 2;
  let status = "Normal";
  if (mean > 0.8) status = "High Risk";
  else if (mean > 0.5) status = "Medium Risk";

  res.json({
    transaction_id: tx_id,
    behavior_risk: status
  });
});

// GET Model Drift status
app.get(["/model-drift", "/api/model-drift"], (req, res) => {
  const txs = readCsvTransactions();
  if (txs.length < 20) {
    return res.json({ status: "Not enough data" });
  }

  const first10 = txs.slice(0, 10).reduce((acc, t) => acc + t.risk, 0) / 10;
  const last10 = txs.slice(-10).reduce((acc, t) => acc + t.risk, 0) / 10;
  const diff = Math.abs(first10 - last10);

  res.json({
    drift_status: diff > 0.3 ? "Drift Detected" : "Model Stable"
  });
});

// GET GNN Fraud Detection (suspicious nodes with degree >= 3)
app.get(["/gnn-fraud-detection", "/api/gnn-fraud-detection"], (req, res) => {
  const degrees: Record<string, number> = {};
  graphEdges.forEach(e => {
    degrees[e.user] = (degrees[e.user] || 0) + 1;
    degrees[e.merchant] = (degrees[e.merchant] || 0) + 1;
  });

  const suspicious_nodes = Object.keys(degrees).filter(node => degrees[node] >= 3);
  res.json({ suspicious_nodes });
});

// GET Profile by user_id
app.get(["/profiles/me", "/api/profiles/me"], (req, res) => {
  const authUser = resolveTokenToUser(req.headers.authorization);
  if (!authUser) {
    return res.status(401).json({ error: "Unauthorized" });
  }

  const profiles = readBehaviorProfiles();
  const profile = profiles[authUser.user_id];

  if (!profile) {
    return res.status(404).json({ error: "Behavior profile not found" });
  }
  res.json(profile);
});

app.get(["/profiles/:user_id", "/api/profiles/:user_id"], (req, res) => {
  const { user_id } = req.params;
  const profiles = readBehaviorProfiles();
  const profile = profiles[user_id];

  if (!profile) {
    return res.status(404).json({ error: "Behavior profile not found" });
  }
  res.json(profile);
});

// GET Statement Transactions for a user (for displaying extracted data on profile page)
app.get(["/statement-transactions/:user_id", "/api/statement-transactions/:user_id"], (req, res) => {
  const { user_id } = req.params;
  const allTxs = readStatementTransactions();
  const userTxs = allTxs.filter(t => t.user_id === user_id);
  res.json(userTxs);
});

// POST Personalized Risk Check
app.post(["/personalized-risk-check", "/api/personalized-risk-check"], (req, res) => {
  const { user_id, amount, merchant, timestamp, upi_id, location } = req.body;
  const profiles = readBehaviorProfiles();
  const profile = profiles[user_id];
  const history = readStatementTransactions().filter(t => t.user_id === user_id);

  const assessment = evaluatePersonalizedRiskLogic(
    profile || null,
    history,
    parseFloat(amount) || 0,
    merchant || "",
    timestamp || new Date().toISOString(),
    upi_id || null,
    location || null
  );

  res.json({
    user_id,
    ...assessment
  });
});

// POST Upload Statement (PDF/CSV)
app.post(["/statement/upload", "/api/statement/upload"], upload.single("file"), async (req, res) => {
  const user_id = req.body.user_id;
  const retain_source = req.body.retain_source === "true";
  const file = req.file;

  if (!user_id) {
    return res.status(400).json({ error: "user_id form field is required" });
  }
  if (!file) {
    return res.status(400).json({ error: "No statement file uploaded" });
  }

  const filename = file.originalname || "statement.csv";
  const content = file.buffer;
  const ext = path.extname(filename).toLowerCase();

  let parsedTxs: any[] = [];
  let source_type = "csv";
  let warnings: string[] = [];

  if (ext === ".csv") {
    // Robust CSV parser
    try {
      const text = content.toString("utf-8");
      const lines = text.split(/\r?\n/);
      if (lines.length > 1) {
        const headers = lines[0].split(",").map(h => h.trim().toLowerCase());
        for (let i = 1; i < lines.length; i++) {
          const line = lines[i].trim();
          if (!line) continue;
          const values = line.split(",").map(v => v.trim());
          const tx: any = {};
          
          headers.forEach((header, idx) => {
            tx[header] = values[idx] || "";
          });

          // Normalize fields
          const amountStr = tx.amount || tx.transaction_amount || tx.debit || tx.credit || tx.withdrawal || tx.deposit || "0";
          const amountVal = parseFloat(amountStr) || 0;
          let dateVal = tx.date || tx.timestamp || tx.datetime || new Date().toISOString().split("T")[0];
          
          // Convert DD/MM/YYYY or MM/DD/YYYY to YYYY-MM-DD
          if (dateVal.includes("/")) {
            const parts = dateVal.split("/");
            if (parts.length === 3 && parts[2].length === 4) {
              // Assume DD/MM/YYYY
              dateVal = `${parts[2]}-${parts[1].padStart(2, "0")}-${parts[0].padStart(2, "0")}`;
            }
          } else if (dateVal.includes("-") && dateVal.split("-")[0].length !== 4) {
             const parts = dateVal.split("-");
             if (parts.length === 3 && parts[2].length === 4) {
               dateVal = `${parts[2]}-${parts[1].padStart(2, "0")}-${parts[0].padStart(2, "0")}`;
             }
          }
          
          let timeVal = tx.time || "12:00";
          // Add seconds if missing to make it valid ISO
          if (timeVal.split(":").length === 2) {
             timeVal += ":00";
          }
          const timestamp = `${dateVal}T${timeVal}`;
          const merchantVal = tx.merchant || tx.payee || tx.description || "UNKNOWN_MERCHANT";

          parsedTxs.push({
            timestamp,
            amount: amountVal,
            merchant: merchantVal,
            upi_id: tx.upi_id || tx.upi || tx.vpa || "",
            status: (tx.status || "SUCCESS").toUpperCase(),
            reference_number: tx.reference_number || tx.reference || tx.utr || tx.txn_id || "",
            raw_line: line
          });
        }
      }
    } catch (err) {
      return res.status(400).json({ error: "Failed to parse CSV statement" });
    }
  } else if (ext === ".pdf") {
    source_type = "pdf";
    try {
      // Delegate PDF parsing to the Python backend which uses pdfplumber
      // for robust multi-format extraction (GPay, PhonePe, Paytm, bank statements, etc.)
      console.log("[PDF] Delegating to Python backend for parsing...");
      
      const FormData = (await import("form-data")).default;
      const formData = new FormData();
      formData.append("user_id", user_id);
      formData.append("retain_source", String(retain_source));
      formData.append("file", content, { filename, contentType: "application/pdf" });

      const http = await import("http");
      
      const backendResult: any = await new Promise((resolve, reject) => {
        const options = {
          hostname: "127.0.0.1",
          port: 8000,
          path: "/statement/upload",
          method: "POST",
          headers: formData.getHeaders(),
        };

        const backendReq = http.request(options, (backendRes: any) => {
          let body = "";
          backendRes.on("data", (chunk: string) => { body += chunk; });
          backendRes.on("end", () => {
            try {
              const parsed = JSON.parse(body);
              if (backendRes.statusCode >= 400) {
                reject(new Error(parsed.detail || parsed.error || "Python backend returned an error"));
              } else {
                resolve(parsed);
              }
            } catch {
              reject(new Error(`Python backend returned invalid JSON: ${body.substring(0, 200)}`));
            }
          });
        });

        backendReq.on("error", (err: Error) => {
          reject(new Error(`Could not reach Python backend at localhost:8000: ${err.message}. Make sure 'python backend/main.py' is running.`));
        });

        formData.pipe(backendReq);
      });

      // The Python backend already saved transactions and built a profile.
      // Return its response directly.
      console.log(`[PDF] Python backend extracted ${backendResult.transactions_extracted || 0} transactions`);
      return res.json(backendResult);

    } catch(err: any) {
      console.error("[PDF] Python backend delegation failed:", err.message);
      return res.status(400).json({ error: "Failed to parse PDF", details: err.message });
    }
  } else {
    return res.status(400).json({ error: "Unsupported file type. Upload a PDF or CSV statement." });
  }

  if (parsedTxs.length === 0) {
    return res.json({
      user_id,
      statement_id: null,
      source_type,
      transactions_extracted: 0,
      warnings,
      profile_created: false
    });
  }

  const statement_id = `stmt_${Math.random().toString(36).substr(2, 8)}`;
  
  // Save statement transactions
  const statementRecords: StatementTransaction[] = parsedTxs.map(tx => ({
    statement_id,
    user_id,
    timestamp: tx.timestamp,
    amount: tx.amount,
    merchant: tx.merchant,
    upi_id: tx.upi_id,
    status: tx.status,
    reference_number: tx.reference_number,
    source_type,
    raw_line: tx.raw_line,
    created_at: new Date().toISOString()
  }));

  saveStatementTransactions(statementRecords);

  // Generate Profile
  const userTxs = readStatementTransactions().filter(t => t.user_id === user_id);
  const profile = generateBehaviorProfileLogic(user_id, userTxs, source_type);
  saveBehaviorProfile(user_id, profile);

  if (retain_source) {
    const uploadPathDir = path.join(DATA_DIR, "uploaded_statements");
    if (!fs.existsSync(uploadPathDir)) {
      fs.mkdirSync(uploadPathDir, { recursive: true });
    }
    const outputName = `${user_id}_${statement_id}_${filename}`;
    fs.writeFileSync(path.join(uploadPathDir, outputName), content);
  }

  res.json({
    user_id,
    statement_id,
    source_type,
    transactions_extracted: parsedTxs.length,
    warnings,
    profile_created: true,
    profile
  });
});

// -----------------------------------------------------------------------------
// ANALYTICS & ASSESSMENT ENGINES
// -----------------------------------------------------------------------------

function generateBehaviorProfileLogic(userId: string, txs: StatementTransaction[], sourceType: string): BehaviorProfile {
  const transaction_count = txs.length;
  if (transaction_count === 0) {
    return {
      user_id: userId,
      transaction_count: 0,
      avg_amount: 0,
      max_amount: 0,
      min_amount: 0,
      most_active_hour: null,
      night_transactions: 0,
      weekend_transactions: 0,
      favorite_merchants: [],
      average_daily_transactions: 0,
      failed_transactions: 0,
      known_upi_ids: [],
      merchant_frequency: {},
      hourly_distribution: {},
      monthly_totals: {},
      source_type: sourceType,
      updated_at: new Date().toISOString()
    };
  }

  const amounts = txs.map(t => t.amount);
  const avg_amount = parseFloat((amounts.reduce((sum, val) => sum + val, 0) / transaction_count).toFixed(2));
  const max_amount = Math.max(...amounts);
  const min_amount = Math.min(...amounts);

  // Hourly profile & distributions
  const hourly_distribution: Record<string, number> = {};
  let night_transactions = 0;
  let weekend_transactions = 0;
  const merchant_frequency: Record<string, number> = {};
  const monthly_totals: Record<string, number> = {};
  const upi_ids_set = new Set<string>();
  let failed_transactions = 0;

  txs.forEach(t => {
    if (t.status === "FAILED" || t.status === "FAILURE") {
      failed_transactions++;
    }
    if (t.upi_id) {
      upi_ids_set.add(t.upi_id);
    }
    if (t.merchant) {
      merchant_frequency[t.merchant] = (merchant_frequency[t.merchant] || 0) + 1;
    }

    try {
      const date = new Date(t.timestamp);
      const hour = date.getHours();
      hourly_distribution[hour.toString()] = (hourly_distribution[hour.toString()] || 0) + 1;
      
      if (hour < 6 || hour >= 22) {
        night_transactions++;
      }
      
      const day = date.getDay();
      if (day === 0 || day === 6) {
        weekend_transactions++;
      }

      // Monthly aggregates
      const yearMonth = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
      monthly_totals[yearMonth] = (monthly_totals[yearMonth] || 0) + t.amount;
    } catch {}
  });

  // Calculate most active hour
  let most_active_hour: number | null = null;
  let maxHourCount = 0;
  Object.keys(hourly_distribution).forEach(h => {
    if (hourly_distribution[h] > maxHourCount) {
      maxHourCount = hourly_distribution[h];
      most_active_hour = parseInt(h);
    }
  });

  // Favorite merchants
  const favorite_merchants = Object.keys(merchant_frequency)
    .sort((a, b) => merchant_frequency[b] - merchant_frequency[a])
    .slice(0, 5);

  // Avg daily transactions (group by date)
  const dateCounts: Record<string, number> = {};
  txs.forEach(t => {
    try {
      const dateStr = new Date(t.timestamp).toISOString().split("T")[0];
      dateCounts[dateStr] = (dateCounts[dateStr] || 0) + 1;
    } catch {}
  });
  const uniqueDays = Object.keys(dateCounts).length;
  const average_daily_transactions = parseFloat((transaction_count / (uniqueDays || 1)).toFixed(2));

  return {
    user_id: userId,
    transaction_count,
    avg_amount,
    max_amount,
    min_amount,
    most_active_hour,
    night_transactions,
    weekend_transactions,
    favorite_merchants,
    average_daily_transactions,
    failed_transactions,
    known_upi_ids: Array.from(upi_ids_set),
    merchant_frequency,
    hourly_distribution,
    monthly_totals,
    source_type: sourceType,
    updated_at: new Date().toISOString()
  };
}

function evaluatePersonalizedRiskLogic(
  profile: BehaviorProfile | null,
  history: StatementTransaction[],
  amount: number,
  merchant: string,
  timestamp: string,
  upi_id: string | null,
  location: string | null
): any {
  let event_time = new Date();
  try {
    event_time = new Date(timestamp);
  } catch {}

  if (!profile || profile.transaction_count === 0) {
    const baseline_risk = amount > 10000 ? 35 : 20;
    return {
      risk_score: baseline_risk,
      risk_level: baseline_risk >= 80 ? "HIGH" : baseline_risk >= 50 ? "MEDIUM" : "LOW",
      reasons: [
        "No historical behavior profile found for this user",
        "Upload past UPI or bank statements to enable personalized checks"
      ],
      comparison: {},
      profile_available: false,
      timestamp: event_time.toISOString(),
      merchant,
      location
    };
  }

  const avg_amount = profile.avg_amount;
  const max_amount = profile.max_amount;
  const favorite_merchants = new Set(profile.favorite_merchants);
  const known_upi_ids = new Set(profile.known_upi_ids);
  const most_active_hour = profile.most_active_hour;
  const avg_daily_transactions = profile.average_daily_transactions;

  let score = 5;
  const reasons: string[] = [];
  const comparison: any = {
    average_amount: avg_amount,
    max_amount: max_amount,
    most_active_hour: most_active_hour,
    average_daily_transactions: avg_daily_transactions
  };

  if (avg_amount > 0) {
    const amount_multiple = parseFloat((amount / avg_amount).toFixed(2));
    comparison.amount_multiple = amount_multiple;

    if (amount_multiple >= 15) {
      score += 35;
      reasons.push(`Amount is ${amount_multiple}x higher than the user's average payment`);
    } else if (amount_multiple >= 8) {
      score += 24;
      reasons.push(`Amount is ${amount_multiple}x above the usual pattern`);
    } else if (amount_multiple >= 3) {
      score += 12;
      reasons.push(`Amount is materially above the user's average transaction size`);
    }
  }

  if (max_amount > 0 && amount > max_amount) {
    score += 15;
    reasons.push("Amount is higher than any previously seen transaction in the uploaded statements");
  }

  const merchantKey = merchant.trim();
  const seenInHistory = history.some(t => t.merchant.toLowerCase() === merchantKey.toLowerCase());
  if (!favorite_merchants.has(merchantKey) && !seenInHistory) {
    score += 20;
    reasons.push("Merchant has not appeared in the user's historical statement profile");
  }

  if (upi_id && !known_upi_ids.has(upi_id)) {
    score += 12;
    reasons.push("UPI ID is new for this user");
  }

  const hour = event_time.getHours();
  if (hour < 6 || hour >= 22) {
    score += 12;
    reasons.push("Transaction time falls in the user's higher-risk night window");
  }

  if (most_active_hour !== null && Math.abs(hour - most_active_hour) >= 8) {
    score += 8;
    reasons.push("Transaction time is far from the user's most active payment hour");
  }

  // Same-day activity velocity count
  const eventDateStr = event_time.toISOString().split("T")[0];
  const sameDayTxs = history.filter(t => {
    try {
      return new Date(t.timestamp).toISOString().split("T")[0] === eventDateStr;
    } catch {
      return false;
    }
  });
  const daily_velocity = sameDayTxs.length + 1;
  comparison.projected_daily_transactions = daily_velocity;

  if (avg_daily_transactions > 0 && daily_velocity > Math.max(avg_daily_transactions * 3, avg_daily_transactions + 6)) {
    score += 18;
    reasons.push("Transaction velocity is unusually high compared with the user's normal daily activity");
  }

  const failed_ratio = profile.failed_transactions / (profile.transaction_count || 1);
  if (failed_ratio > 0.2) {
    score += 5;
    reasons.push("Historical statement profile already contains a high failed transaction ratio");
  }

  const final_score = Math.min(99, Math.round(score));

  if (reasons.length === 0) {
    reasons.push("Payment fits the user's historical amount, merchant, and timing patterns");
  }

  return {
    risk_score: final_score,
    risk_level: final_score >= 80 ? "HIGH" : final_score >= 50 ? "MEDIUM" : "LOW",
    reasons,
    comparison,
    profile_available: true,
    timestamp: event_time.toISOString(),
    merchant,
    location
  };
}

// -----------------------------------------------------------------------------
// VITE DEV SERVER & STATIC ASSETS SETUP
// -----------------------------------------------------------------------------

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
    app.get("*", (req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`Server running on http://localhost:${PORT}`);
  });
}

startServer();
