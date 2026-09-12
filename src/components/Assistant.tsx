import { useEffect, useRef, useState } from "react";
import { Loader2, MessageCircle, Send, ShieldQuestion, X } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { useLastCheck } from "../context/CheckContext";

/**
 * The assistant panel.
 *
 * It explains what the app found; it cannot act. Every verdict comes from the
 * deterministic engine, and this panel is a way of asking about one in plain
 * language — so it is presented beside the result, never in place of it, and
 * the disclaimer under the input says as much.
 *
 * The answer text is rendered as plain text, never as HTML or markdown links.
 * The model is reading attacker-written content by design (that is what a scam
 * message is), and a model that has been talked into emitting a link should not
 * be handed a renderer that makes it clickable.
 */

interface Turn {
  role: "user" | "assistant";
  content: string;
}

interface ChatResponse {
  answer: string;
  model?: string | null;
  available: boolean;
  detail?: string | null;
}

const STARTERS = [
  "Why did this get blocked?",
  "What does this finding mean?",
  "I think I've been scammed — what do I do?",
  "How do UPI QR scams work?",
];

export default function Assistant() {
  const { api } = useAuth();
  const { lastCheck } = useLastCheck();

  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [configured, setConfigured] = useState<boolean | null>(null);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  // Asked once, so the panel can say "not set up" rather than offering a box
  // that answers every question with an error.
  useEffect(() => {
    let cancelled = false;
    api<{ available: boolean }>("/api/chat/status")
      .then((r) => { if (!cancelled) setConfigured(r.available); })
      .catch(() => { if (!cancelled) setConfigured(false); });
    return () => { cancelled = true; };
  }, [api]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns, sending]);

  // Escape closes the panel, which is the one keyboard affordance people try.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const send = async (text?: string) => {
    const question = (text ?? draft).trim();
    if (!question || sending) return;

    const history = turns.slice(-16);
    setTurns((t) => [...t, { role: "user", content: question }]);
    setDraft("");
    setSending(true);
    try {
      const r = await api<ChatResponse>("/api/chat", {
        method: "POST",
        body: JSON.stringify({
          message: question,
          history,
          // The result on screen, so "why was this blocked?" has a referent.
          // Echoed evidence only — the backend re-derives everything about the
          // person's own history from their token.
          check_result: lastCheck ?? null,
        }),
      });
      setTurns((t) => [...t, { role: "assistant", content: r.answer }]);
      if (r.available === false) setConfigured(false);
    } catch (err: any) {
      setTurns((t) => [
        ...t,
        { role: "assistant", content: err?.message || "I couldn't answer that just now." },
      ]);
    } finally {
      setSending(false);
    }
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Open the assistant"
        className="fixed bottom-5 right-5 z-40 h-14 w-14 rounded-full grid place-items-center transition-transform hover:scale-105"
        style={{
          background: "var(--brand)",
          color: "white",
          boxShadow: "0 8px 28px color-mix(in oklab, var(--brand) 45%, transparent)",
        }}
      >
        <MessageCircle className="h-6 w-6" />
      </button>
    );
  }

  return (
    <div
      role="dialog"
      aria-label="Assistant"
      className="fixed z-40 flex flex-col overflow-hidden
                 inset-x-3 bottom-3 top-20
                 sm:inset-auto sm:bottom-5 sm:right-5 sm:top-auto sm:w-[400px] sm:h-[560px]"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--line)",
        borderRadius: 20,
        boxShadow: "0 18px 50px color-mix(in oklab, black 28%, transparent)",
      }}
    >
      <header
        className="flex items-center justify-between px-4 py-3 shrink-0"
        style={{ borderBottom: "1px solid var(--line)" }}
      >
        <div className="flex items-center gap-2">
          <ShieldQuestion className="h-5 w-5" style={{ color: "var(--brand)" }} />
          <span className="font-bold" style={{ color: "var(--ink)" }}>Ask about this check</span>
        </div>
        <button type="button" onClick={() => setOpen(false)} aria-label="Close"
                style={{ color: "var(--ink-subtle)" }}>
          <X className="h-5 w-5" />
        </button>
      </header>

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {configured === false && (
          <div
            className="rounded-xl p-3 text-sm"
            style={{
              background: "color-mix(in oklab, var(--warn) 10%, transparent)",
              border: "1px solid color-mix(in oklab, var(--warn) 28%, transparent)",
              color: "var(--ink-muted)",
            }}
          >
            No language model is connected, so I can only give the standard answers.
            Every finding on a result already explains itself in plain language.
          </div>
        )}

        {turns.length === 0 && (
          <div className="space-y-3">
            <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
              I can explain what a check found, how a scam works, and what to do if you
              have already sent money.
              {lastCheck && (
                <> I can see your last check on <strong>{lastCheck.payee?.vpa}</strong>.</>
              )}
            </p>
            <div className="flex flex-wrap gap-2">
              {STARTERS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => send(s)}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium text-left"
                  style={{
                    background: "var(--inset)",
                    border: "1px solid var(--line)",
                    color: "var(--ink-muted)",
                  }}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {turns.map((t, i) => (
          <div key={i} className={t.role === "user" ? "flex justify-end" : "flex justify-start"}>
            <div
              // whitespace-pre-wrap renders the model's newlines but nothing
              // else: no markdown, no HTML, no clickable links.
              className="rounded-2xl px-3.5 py-2.5 text-sm max-w-[86%] whitespace-pre-wrap break-words"
              style={
                t.role === "user"
                  ? { background: "var(--brand)", color: "white" }
                  : {
                      background: "var(--inset)",
                      border: "1px solid var(--line)",
                      color: "var(--ink)",
                    }
              }
            >
              {t.content}
            </div>
          </div>
        ))}

        {sending && (
          <div className="flex items-center gap-2 text-sm" style={{ color: "var(--ink-subtle)" }}>
            <Loader2 className="h-4 w-4 animate-spin" /> Thinking…
          </div>
        )}
      </div>

      <div className="px-3 pt-2 pb-3 shrink-0" style={{ borderTop: "1px solid var(--line)" }}>
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            rows={1}
            placeholder="Ask a question…"
            className="flex-1 px-3 py-2 rounded-xl text-sm resize-none max-h-28"
            style={{
              background: "var(--inset)",
              border: "1px solid var(--line)",
              color: "var(--ink)",
            }}
          />
          <button
            type="button"
            onClick={() => send()}
            disabled={sending || !draft.trim()}
            aria-label="Send"
            className="h-9 w-9 rounded-xl grid place-items-center shrink-0 disabled:opacity-40"
            style={{ background: "var(--brand)", color: "white" }}
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
        <p className="text-[11px] mt-2 leading-snug" style={{ color: "var(--ink-subtle)" }}>
          I explain what the checks found — I can't approve, block or make a payment, and
          I'll never ask for a PIN or an OTP. Verdicts come from the app, not from me.
        </p>
      </div>
    </div>
  );
}
