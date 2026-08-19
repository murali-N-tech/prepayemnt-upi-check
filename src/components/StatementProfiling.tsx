import React, { useState } from "react";
import { Upload, AlertCircle, FileText, CheckCircle2, ArrowRight, Loader2, FileUp, Info } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { getApiUrl } from "../services/apiConfig";

interface StatementProfilingProps {
  onNavigate?: (page: string) => void;
}

export default function StatementProfiling({ onNavigate }: StatementProfilingProps) {
  const { userId, token } = useAuth();
  const [retainSource, setRetainSource] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<boolean>(false);
  const [extractedCount, setExtractedCount] = useState<number>(0);
  const [sourceType, setSourceType] = useState<string>("");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [dragActive, setDragActive] = useState(false);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0]);
      setError(null);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const dropped = e.dataTransfer.files[0];
      const ext = dropped.name.toLowerCase().split(".").pop();
      if (ext === "pdf" || ext === "csv") {
        setFile(dropped);
        setError(null);
      } else {
        setError("Only PDF and CSV files are supported.");
      }
    }
  };

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!userId) {
      setError("User session invalid. Please log in.");
      return;
    }
    if (!file) {
      setError("Please upload a CSV or PDF statement file");
      return;
    }

    setLoading(true);
    setError(null);
    setSuccess(false);
    setWarnings([]);

    const formData = new FormData();
    formData.append("user_id", userId);
    formData.append("retain_source", String(retainSource));
    formData.append("file", file);

    try {
      const res = await fetch(getApiUrl("/api/statement/upload"), {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${token}`
        },
        body: formData,
      });

      if (!res.ok) {
        const text = await res.text();
        let detail = text;
        try {
          const json = JSON.parse(text);
          detail = json.details || json.detail || json.error || text;
        } catch {}
        throw new Error(detail || "Upload failed");
      }

      const result = await res.json();
      if (result.profile || result.transactions_extracted > 0) {
        setSuccess(true);
        setExtractedCount(result.transactions_extracted || 0);
        setSourceType(result.source_type || "");
        setWarnings(result.warnings || []);
      } else {
        setError("Could not extract any transactions from the uploaded file.");
        setWarnings(result.warnings || []);
      }
    } catch (err: any) {
      setError(err.message || "An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-8 animate-fade-in" id="statement-profiling-container">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-white mb-2">Upload Statement</h1>
        <p className="text-slate-400">
          Upload a UPI or bank statement (PDF/CSV) to extract transactional features and synthesize your personalized payment behavior profile.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Upload Form Card */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 h-fit" id="upload-card">
          <h2 className="text-xl font-semibold text-white mb-1">Generate Behaviour Profile</h2>
          <p className="text-xs text-slate-500 mb-5">Supports: Google Pay, PhonePe, Paytm, SBI, HDFC, ICICI, Axis, Bank of Baroda, and generic bank PDFs</p>
          
          <form onSubmit={handleUpload} className="space-y-5">
            <div className="flex items-center">
              <input
                id="retain"
                type="checkbox"
                checked={retainSource}
                onChange={(e) => setRetainSource(e.target.checked)}
                className="h-4 w-4 bg-slate-950 border border-slate-800 rounded text-indigo-600 focus:ring-indigo-500"
              />
              <label htmlFor="retain" className="ml-2 block text-sm text-slate-300">
                Retain original statement file on server
              </label>
            </div>

            <div
              onDrop={handleDrop}
              onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
              onDragLeave={() => setDragActive(false)}
              className={`border-2 border-dashed rounded-lg p-8 transition cursor-pointer text-center relative ${
                dragActive
                  ? "border-indigo-500 bg-indigo-500/5"
                  : file
                    ? "border-emerald-500/40 bg-emerald-500/5"
                    : "border-slate-800 bg-slate-950/50 hover:bg-slate-950 hover:border-slate-700"
              }`}
            >
              <input
                type="file"
                accept=".pdf,.csv"
                onChange={handleFileChange}
                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
              />
              {file ? (
                <>
                  <FileUp className="mx-auto h-10 w-10 text-emerald-400 mb-2" />
                  <p className="text-sm font-semibold text-emerald-300">{file.name}</p>
                  <p className="text-xs text-slate-500 mt-1">{(file.size / 1024).toFixed(1)} KB · Click or drop to replace</p>
                </>
              ) : (
                <>
                  <Upload className="mx-auto h-12 w-12 text-slate-500 mb-2" />
                  <p className="text-sm font-medium text-slate-300">Click to select or drag PDF / CSV</p>
                  <p className="text-xs text-slate-500 mt-1">PDF bank statement or CSV up to 10MB</p>
                </>
              )}
            </div>

            {error && (
              <div className="bg-red-500/10 border border-red-500/20 text-red-400 text-sm rounded-lg p-3 flex items-start gap-2">
                <AlertCircle className="h-5 w-5 shrink-0 mt-0.5" />
                <span>{error}</span>
              </div>
            )}

            {warnings.length > 0 && !success && (
              <div className="bg-amber-500/10 border border-amber-500/20 text-amber-400 text-sm rounded-lg p-3 flex items-start gap-2">
                <Info className="h-5 w-5 shrink-0 mt-0.5" />
                <div>
                  {warnings.map((w, i) => <p key={i} className="text-xs">{w}</p>)}
                </div>
              </div>
            )}

            <button
              type="submit"
              disabled={loading || !file}
              className="w-full py-2.5 px-4 bg-indigo-600 hover:bg-indigo-500 disabled:bg-indigo-800 disabled:opacity-60 text-white font-medium rounded-lg shadow-sm transition flex items-center justify-center gap-2"
            >
              {loading ? (
                <>
                  <Loader2 className="h-5 w-5 animate-spin" />
                  Extracting transactions…
                </>
              ) : (
                <>
                  <FileText className="h-4 w-4" />
                  Upload & Extract
                </>
              )}
            </button>
          </form>
        </div>
        
        {/* Success Panel */}
        <div className="h-fit">
          {success && (
            <div className="bg-gradient-to-br from-emerald-500/10 to-slate-900 border border-emerald-500/20 text-emerald-400 rounded-xl p-6 animate-fade-in">
              <div className="flex items-start gap-4 mb-5">
                <CheckCircle2 className="h-8 w-8 text-emerald-400 shrink-0 mt-1" />
                <div>
                  <h3 className="text-lg font-bold text-emerald-300 mb-1">Profile Successfully Compiled</h3>
                  <p className="text-emerald-400/80 text-sm">
                    Behavior profile generated from <span className="font-bold text-emerald-300">{extractedCount}</span> extracted transactions.
                  </p>
                  {sourceType && (
                    <p className="text-xs text-emerald-400/60 mt-1">
                      Source: <span className="font-mono">{sourceType}</span>
                    </p>
                  )}
                </div>
              </div>

              {warnings.length > 0 && (
                <div className="bg-amber-500/10 border border-amber-500/20 text-amber-300 text-xs rounded-lg p-3 mb-4">
                  {warnings.map((w, i) => <p key={i}>{w}</p>)}
                </div>
              )}

              {/* Summary stats */}
              <div className="grid grid-cols-2 gap-3 mb-5">
                <div className="bg-slate-900/60 rounded-lg p-3 border border-slate-800/50">
                  <div className="text-2xl font-bold text-white">{extractedCount}</div>
                  <div className="text-xs text-emerald-400/60">Transactions</div>
                </div>
                <div className="bg-slate-900/60 rounded-lg p-3 border border-slate-800/50">
                  <div className="text-2xl font-bold text-white">{sourceType.includes("pdf") ? "PDF" : "CSV"}</div>
                  <div className="text-xs text-emerald-400/60">Format</div>
                </div>
              </div>

              <button
                onClick={() => onNavigate?.("User Profile")}
                className="w-full py-2.5 px-4 bg-emerald-600 hover:bg-emerald-500 text-white font-medium rounded-lg shadow-sm transition flex items-center justify-center gap-2"
              >
                View Profile & Transactions
                <ArrowRight className="h-4 w-4" />
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
