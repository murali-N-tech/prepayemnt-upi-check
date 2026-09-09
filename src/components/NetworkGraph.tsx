import { useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, ArrowLeft, RefreshCw, Search, Share2, X } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { useChartTheme } from "../lib/chartTheme";

interface Edge {
  user: string;      // payer
  merchant: string;  // payee
}

interface Flag {
  node: string;
  fan_in: number;
  reasons: string[];
}

/* ── Why this looks the way it does ────────────────────────────────────────────

   The previous version drew every node on one circle with every label switched
   on. At this dataset's size that is a black disc: a thousand overlapping
   labels and tens of thousands of crossing edges, from which nothing can be
   read. More rendering effort would not have fixed it — the layout was showing
   more than a person can look at.

   So the view starts by answering a question instead of showing everything:
   which payees are collecting money from many different people? That list is
   the entry point, and the canvas draws ONE payee's neighbourhood at a time.

   The layout is bipartite — payers in a left column, payees in a right one —
   because that is what the data actually is. A payer→payee graph has no
   payer-to-payer edges, so a circle spends all its space on crossings that
   carry no information, while two columns make fan-in directly visible: a
   mule account is the payee with a dozen lines converging on it.
   ─────────────────────────────────────────────────────────────────────────── */

const MAX_PAYERS = 22;   // beyond this the rows stop being labellable
const MAX_PAYEES = 12;
const ROW_H = 26;
const TOP_PAD = 44;
const WIDTH = 900;
const PAYER_X = 260;
const PAYEE_X = 640;

function truncate(value: string, max = 26) {
  return value.length <= max ? value : value.slice(0, max - 1) + "…";
}

export default function NetworkGraph() {
  const chart = useChartTheme();
  const { api } = useAuth();
  const [edges, setEdges] = useState<Edge[]>([]);
  const [flags, setFlags] = useState<Flag[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [focus, setFocus] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const [minPayers, setMinPayers] = useState(2);
  const listRef = useRef<HTMLDivElement>(null);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [edgesData, graphData] = await Promise.all([
        api<{ edges?: Edge[] }>("/api/fraud-graph"),
        api<{ suspicious_nodes?: string[]; details?: Flag[] }>("/api/gnn-fraud-detection"),
      ]);
      setEdges(Array.isArray(edgesData?.edges) ? edgesData.edges : []);
      setFlags(Array.isArray(graphData?.details) ? graphData.details : []);
    } catch (err: any) {
      setError(err.message || "Failed to load the payment graph");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  /* ── Index the edge list once ─────────────────────────────────────────── */

  const index = useMemo(() => {
    const payeeToPayers = new Map<string, Set<string>>();
    const payerToPayees = new Map<string, Set<string>>();

    for (const e of edges) {
      if (!e?.user || !e?.merchant) continue;
      if (!payeeToPayers.has(e.merchant)) payeeToPayers.set(e.merchant, new Set());
      payeeToPayers.get(e.merchant)!.add(e.user);
      if (!payerToPayees.has(e.user)) payerToPayees.set(e.user, new Set());
      payerToPayees.get(e.user)!.add(e.merchant);
    }
    return { payeeToPayers, payerToPayees };
  }, [edges]);

  const flagged = useMemo(() => new Set(flags.map((f) => f.node)), [flags]);

  /** Every payee, ranked by the thing that matters: how many different people
   *  paid it, and how many of those paid nobody else. */
  const ranked = useMemo(() => {
    const rows = [...index.payeeToPayers.entries()].map(([payee, payers]) => {
      let oneShot = 0;
      for (const p of payers) {
        if ((index.payerToPayees.get(p)?.size ?? 0) === 1) oneShot++;
      }
      return {
        payee,
        fanIn: payers.size,
        oneShot,
        oneShotShare: payers.size ? oneShot / payers.size : 0,
        flagged: flagged.has(payee),
      };
    });

    rows.sort(
      (a, b) =>
        Number(b.flagged) - Number(a.flagged) ||
        b.fanIn - a.fanIn ||
        b.oneShot - a.oneShot
    );
    return rows;
  }, [index, flagged]);

  const visibleRows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return ranked.filter(
      (r) =>
        r.fanIn >= minPayers &&
        (!onlyFlagged || r.flagged) &&
        (!q || r.payee.toLowerCase().includes(q))
    );
  }, [ranked, query, onlyFlagged, minPayers]);

  // Land on something worth looking at rather than an empty canvas.
  useEffect(() => {
    if (!focus && visibleRows.length) setFocus(visibleRows[0].payee);
  }, [visibleRows, focus]);

  /* ── The neighbourhood actually drawn ─────────────────────────────────── */

  const view = useMemo(() => {
    if (!focus) return null;
    const payerSet = index.payeeToPayers.get(focus);
    if (!payerSet) return null;

    const payers = [...payerSet].map((id) => {
      const paid = index.payerToPayees.get(id) ?? new Set<string>();
      return { id, alsoPaid: [...paid].filter((m) => m !== focus), oneShot: paid.size === 1 };
    });

    // One-shot payers first: a wall of people who paid this account and
    // nothing else is the signature worth seeing at the top.
    payers.sort(
      (a, b) => Number(b.oneShot) - Number(a.oneShot) || a.alsoPaid.length - b.alsoPaid.length
    );
    const shownPayers = payers.slice(0, MAX_PAYERS);

    // Payees those same payers also paid — how a ring becomes visible.
    const coCount = new Map<string, number>();
    for (const p of shownPayers) {
      for (const m of p.alsoPaid) coCount.set(m, (coCount.get(m) ?? 0) + 1);
    }
    const coPayees = [...coCount.entries()]
      .sort((a, b) => b[1] - a[1] || Number(flagged.has(b[0])) - Number(flagged.has(a[0])))
      .slice(0, MAX_PAYEES - 1)
      .map(([id, shared]) => ({ id, shared }));

    const payeeColumn = [{ id: focus, shared: 0, isFocus: true }, ...coPayees.map((c) => ({ ...c, isFocus: false }))];

    const rows = Math.max(shownPayers.length, payeeColumn.length);
    const height = TOP_PAD * 2 + Math.max(rows, 1) * ROW_H;
    // Both columns are spread over the SAME vertical span. Stacking the two
    // or three payees at the top instead left every link converging into one
    // corner, which is exactly the braid this rewrite exists to remove.
    const span = Math.max(rows, 1) * ROW_H;
    const spread = (count: number, i: number) =>
      count <= 1 ? TOP_PAD + span / 2 : TOP_PAD + (span / count) * (i + 0.5);

    const payerY = new Map(
      shownPayers.map((p, i) => [p.id, spread(shownPayers.length, i)])
    );
    const payeeY = new Map(
      payeeColumn.map((p, i) => [p.id, spread(payeeColumn.length, i)])
    );

    const links: { payer: string; payee: string; toFocus: boolean }[] = [];
    for (const p of shownPayers) {
      links.push({ payer: p.id, payee: focus, toFocus: true });
      for (const m of p.alsoPaid) {
        if (payeeY.has(m)) links.push({ payer: p.id, payee: m, toFocus: false });
      }
    }

    return {
      payers: shownPayers,
      payeeColumn,
      hiddenPayers: payers.length - shownPayers.length,
      payerY,
      payeeY,
      links,
      height,
    };
  }, [focus, index, flagged]);

  const focusFlag = flags.find((f) => f.node === focus);
  const focusRow = ranked.find((r) => r.payee === focus);

  const isDimmed = (id: string) => {
    if (!hover || !view) return false;
    if (id === hover) return false;
    return !view.links.some(
      (l) =>
        (l.payer === hover && l.payee === id) || (l.payee === hover && l.payer === id)
    );
  };

  /* ── Render ───────────────────────────────────────────────────────────── */

  return (
    <div className="space-y-6" id="network-graph-container">
      <div className="flex flex-col md:flex-row md:items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-ink">Payment Network</h1>
          <p className="mt-1.5 text-ink-muted max-w-2xl leading-relaxed">
            Who pays whom. Pick a payee on the left and the canvas draws just that
            account's neighbourhood — the people who paid it, and any other payees
            those same people paid.
          </p>
        </div>

        <button
          onClick={fetchData}
          disabled={loading}
          className="flex items-center gap-2 px-3.5 py-2 rounded-lg border border-line bg-surface text-sm text-ink-muted hover:text-ink hover:bg-raised transition shrink-0"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Reload
        </button>
      </div>

      {error && (
        <div className="flex items-start gap-3 rounded-xl border border-danger/25 bg-danger/5 p-4">
          <AlertCircle className="h-5 w-5 text-danger shrink-0 mt-0.5" />
          <p className="text-sm text-ink-muted">{error}</p>
        </div>
      )}

      {/* Three numbers, stated plainly. */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: "Payers", value: index.payerToPayees.size, note: "distinct senders" },
          { label: "Payees", value: index.payeeToPayers.size, note: "distinct receivers" },
          { label: "Payments", value: edges.length, note: "payer → payee links" },
          {
            label: "Flagged payees",
            value: flags.length,
            note: "by the graph rules",
            danger: true,
          },
        ].map((s) => (
          <div
            key={s.label}
            className={`rounded-xl border p-4 ${
              s.danger && s.value > 0
                ? "border-danger/25 bg-danger/5"
                : "border-line bg-surface"
            }`}
          >
            <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-subtle">
              {s.label}
            </div>
            <div
              className={`mt-1 text-2xl font-bold tabular-nums ${
                s.danger && s.value > 0 ? "text-danger" : "text-ink"
              }`}
            >
              {s.value.toLocaleString("en-IN")}
            </div>
            <div className="text-[11px] text-ink-subtle mt-0.5">{s.note}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[22rem_1fr] gap-5 items-start">
        {/* ── Ranked payees ─────────────────────────────────────────────── */}
        <div className="rounded-xl border border-line bg-surface overflow-hidden">
          <div className="p-4 border-b border-line space-y-3">
            <div>
              <h2 className="font-semibold text-ink">Where money collects</h2>
              <p className="text-xs text-ink-subtle mt-0.5">
                Payees ranked by how many different people paid them.
              </p>
            </div>

            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-ink-subtle" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Find a payee"
                className="w-full pl-9 pr-8 py-2 rounded-lg bg-inset border border-line text-sm text-ink placeholder-ink-subtle"
              />
              {query && (
                <button
                  onClick={() => setQuery("")}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded text-ink-subtle hover:text-ink"
                  aria-label="Clear search"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>

            <div className="flex items-center justify-between gap-3">
              <label className="flex items-center gap-2 text-xs text-ink-muted cursor-pointer">
                <input
                  type="checkbox"
                  checked={onlyFlagged}
                  onChange={(e) => setOnlyFlagged(e.target.checked)}
                  className="accent-indigo-500"
                />
                Only flagged
              </label>
              <label className="flex items-center gap-2 text-xs text-ink-muted">
                <span className="whitespace-nowrap">Min payers</span>
                <input
                  type="range"
                  min={1}
                  max={10}
                  value={minPayers}
                  onChange={(e) => setMinPayers(parseInt(e.target.value))}
                  className="w-20 accent-indigo-500"
                />
                <span className="tabular-nums w-4 text-ink">{minPayers}</span>
              </label>
            </div>
          </div>

          <div ref={listRef} className="max-h-[26rem] overflow-y-auto divide-y divide-line">
            {visibleRows.length === 0 ? (
              <p className="p-4 text-sm text-ink-subtle">
                Nothing matches those filters.
              </p>
            ) : (
              visibleRows.slice(0, 200).map((row) => {
                const active = row.payee === focus;
                return (
                  <button
                    key={row.payee}
                    onClick={() => setFocus(row.payee)}
                    className={`w-full text-left px-4 py-2.5 transition ${
                      active ? "bg-brand/10" : "hover:bg-raised"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className={`h-1.5 w-1.5 rounded-full shrink-0 ${
                          row.flagged ? "bg-danger" : "bg-ok"
                        }`}
                      />
                      <span
                        className={`font-mono text-xs truncate ${
                          active ? "text-brand font-semibold" : "text-ink"
                        }`}
                        title={row.payee}
                      >
                        {row.payee}
                      </span>
                    </div>
                    <div className="mt-1 pl-3.5 text-[11px] text-ink-subtle">
                      {row.fanIn} payer{row.fanIn === 1 ? "" : "s"}
                      {row.oneShot > 0 && (
                        <>
                          {" · "}
                          <span className={row.oneShotShare > 0.7 ? "text-warn" : ""}>
                            {row.oneShot} paid nobody else
                          </span>
                        </>
                      )}
                    </div>
                  </button>
                );
              })
            )}
          </div>

          {visibleRows.length > 200 && (
            <div className="px-4 py-2 border-t border-line text-[11px] text-ink-subtle">
              Showing the top 200 of {visibleRows.length}. Narrow the search to see more.
            </div>
          )}
        </div>

        {/* ── Canvas ────────────────────────────────────────────────────── */}
        <div className="rounded-xl border border-line bg-surface overflow-hidden">
          <div className="px-4 py-3 border-b border-line flex flex-wrap items-center gap-x-5 gap-y-2">
            <span className="inline-flex items-center gap-2 text-xs text-ink-muted">
              <span className="h-2.5 w-2.5 rounded-full border-2" style={{ borderColor: chart.brand }} />
              Paid only this payee
            </span>
            <span className="inline-flex items-center gap-2 text-xs text-ink-muted">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: chart.brand }} />
              Also paid others
            </span>
            <span className="inline-flex items-center gap-2 text-xs text-ink-muted">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: chart.ok }} />
              Payee
            </span>
            <span className="inline-flex items-center gap-2 text-xs text-ink-muted">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: chart.danger }} />
              Flagged
            </span>
            <span className="ml-auto text-[11px] text-ink-subtle">
              Hover a node to isolate its links
            </span>
          </div>

          {loading ? (
            <div className="h-[28rem] grid place-items-center">
              <div className="h-8 w-8 border-2 border-brand border-t-transparent rounded-full animate-spin" />
            </div>
          ) : !edges.length ? (
            <div className="h-[28rem] grid place-items-center px-6 text-center">
              <div>
                <Share2 className="h-10 w-10 text-ink-faint mx-auto mb-3" />
                <p className="font-medium text-ink">No payments recorded yet</p>
                <p className="mt-1 text-sm text-ink-subtle max-w-sm">
                  The graph is built from payments the system has seen. Upload a
                  statement or run a few payee checks and this fills in.
                </p>
              </div>
            </div>
          ) : !view ? (
            <div className="h-[28rem] grid place-items-center px-6 text-center">
              <p className="text-sm text-ink-subtle">Pick a payee to draw its neighbourhood.</p>
            </div>
          ) : (
            <>
              {/* What is on screen, in one sentence. */}
              <div className="px-4 py-3 border-b border-line bg-inset">
                <div className="flex items-start gap-2 flex-wrap">
                  {focusRow?.flagged && (
                    <span className="px-2 py-0.5 rounded-md border border-danger/25 bg-danger/10 text-danger text-[10px] font-bold tracking-wide">
                      FLAGGED
                    </span>
                  )}
                  <span className="font-mono text-sm text-ink break-all">{focus}</span>
                </div>
                <p className="mt-1.5 text-xs text-ink-muted">
                  Paid by {focusRow?.fanIn ?? 0} people
                  {focusRow?.oneShot ? `, ${focusRow.oneShot} of whom paid nobody else` : ""}
                  {view.payeeColumn.length > 1
                    ? `. Those payers also paid ${view.payeeColumn.length - 1} other payee${
                        view.payeeColumn.length - 1 === 1 ? "" : "s"
                      }.`
                    : "."}
                  {view.hiddenPayers > 0 && (
                    <span className="text-ink-subtle">
                      {" "}
                      {view.hiddenPayers} more payer{view.hiddenPayers === 1 ? "" : "s"} not
                      drawn.
                    </span>
                  )}
                </p>
              </div>

              <div className="max-h-[42rem] overflow-y-auto">
                <svg
                  viewBox={`0 0 ${WIDTH} ${view.height}`}
                  className="w-full select-none"
                  style={{ height: view.height }}
                  onMouseLeave={() => setHover(null)}
                >
                  <text x={PAYER_X} y={24} textAnchor="middle" fontSize={11} fontWeight={600} fill={chart.axis}>
                    PAYERS
                  </text>
                  <text x={PAYEE_X} y={24} textAnchor="middle" fontSize={11} fontWeight={600} fill={chart.axis}>
                    PAYEES
                  </text>

                  {/* Links */}
                  <g>
                    {[...view.links]
                      .sort((a, b) => Number(a.toFocus) - Number(b.toFocus))
                      .map((l, i) => {
                      const y1 = view.payerY.get(l.payer);
                      const y2 = view.payeeY.get(l.payee);
                      if (y1 === undefined || y2 === undefined) return null;
                      // A link stays lit only when it touches the hovered
                      // node. Requiring BOTH ends to be dimmed left every link
                      // bright, because they all share the focused payee.
                      const dim = !!hover && l.payer !== hover && l.payee !== hover;
                      const mid = (PAYER_X + PAYEE_X) / 2;
                      return (
                        <path
                          key={i}
                          d={`M ${PAYER_X + 8} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${PAYEE_X - 8} ${y2}`}
                          fill="none"
                          stroke={l.toFocus ? chart.brand : chart.warn}
                          strokeWidth={l.toFocus ? 1.5 : 1}
                          opacity={dim ? 0.05 : l.toFocus ? 0.55 : 0.3}
                          className="transition-opacity"
                        />
                      );
                    })}
                  </g>

                  {/* Payers */}
                  <g>
                    {view.payers.map((p) => {
                      const y = view.payerY.get(p.id)!;
                      const dim = isDimmed(p.id);
                      return (
                        <g
                          key={p.id}
                          opacity={dim ? 0.25 : 1}
                          className="transition-opacity cursor-default"
                          onMouseEnter={() => setHover(p.id)}
                        >
                          <title>
                            {p.id} — paid {p.alsoPaid.length + 1} payee
                            {p.alsoPaid.length ? "s" : ""}
                          </title>
                          <text
                            x={PAYER_X - 18}
                            y={y + 4}
                            textAnchor="end"
                            fontSize={11}
                            fill={hover === p.id ? chart.nodeLabel : chart.axis}
                            className="font-mono"
                          >
                            {truncate(p.id, 30)}
                          </text>
                          <circle
                            cx={PAYER_X}
                            cy={y}
                            r={5.5}
                            fill={p.oneShot ? "transparent" : chart.brand}
                            stroke={chart.brand}
                            strokeWidth={2}
                          />
                        </g>
                      );
                    })}
                  </g>

                  {/* Payees */}
                  <g>
                    {view.payeeColumn.map((p) => {
                      const y = view.payeeY.get(p.id)!;
                      const dim = isDimmed(p.id);
                      const isFlagged = flagged.has(p.id);
                      const size = p.isFocus ? 9 : 7;
                      return (
                        <g
                          key={p.id}
                          opacity={dim ? 0.25 : 1}
                          className="transition-opacity cursor-pointer"
                          onMouseEnter={() => setHover(p.id)}
                          onClick={() => !p.isFocus && setFocus(p.id)}
                        >
                          <title>
                            {p.id}
                            {p.isFocus ? " — in focus" : ` — shares ${p.shared} payer(s)`}
                          </title>
                          <rect
                            x={PAYEE_X - size}
                            y={y - size}
                            width={size * 2}
                            height={size * 2}
                            rx={2.5}
                            fill={isFlagged ? chart.danger : chart.ok}
                            stroke={p.isFocus ? chart.nodeLabel : "none"}
                            strokeWidth={p.isFocus ? 2 : 0}
                          />
                          <text
                            x={PAYEE_X + 18}
                            y={y + 4}
                            fontSize={11}
                            fontWeight={p.isFocus ? 700 : 400}
                            fill={p.isFocus || hover === p.id ? chart.nodeLabel : chart.axis}
                            className="font-mono"
                          >
                            {truncate(p.id, 28)}
                          </text>
                        </g>
                      );
                    })}
                  </g>
                </svg>
              </div>

              {view.payeeColumn.length > 1 && (
                <div className="px-4 py-2.5 border-t border-line text-[11px] text-ink-subtle">
                  Amber links are payments to a <em>different</em> payee. Several of
                  them converging on the same few accounts is what a collection ring
                  looks like — click one to follow it.
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Why the focused payee was flagged — beside the picture, not in a
          separate list the reader has to match up by eye. */}
      {focusFlag && (
        <div className="rounded-xl border border-danger/25 bg-danger/5 p-5">
          <div className="flex items-center gap-2 mb-3">
            <AlertCircle className="h-4 w-4 text-danger" />
            <h3 className="font-semibold text-ink">Why this payee was flagged</h3>
          </div>
          <ul className="space-y-2">
            {focusFlag.reasons.map((r, i) => (
              <li key={i} className="flex gap-2.5 text-sm text-ink-muted leading-relaxed">
                <span className="mt-1.5 h-1.5 w-1.5 rounded-full bg-danger shrink-0" />
                {r}
              </li>
            ))}
          </ul>
          <p className="mt-4 pt-3 border-t border-danger/20 text-xs text-ink-subtle">
            These come from graph rules — fan-in, one-shot payers, shared payers
            between accounts — not from a neural network. Each result carries the
            reason it was returned.
          </p>
        </div>
      )}

      {flags.length > 0 && !focusFlag && (
        <button
          onClick={() => {
            setOnlyFlagged(true);
            setFocus(flags[0].node);
            listRef.current?.scrollTo({ top: 0 });
          }}
          className="w-full sm:w-auto inline-flex items-center gap-2 px-4 py-2.5 rounded-lg border border-danger/25 bg-danger/5 text-sm text-ink hover:bg-danger/10 transition"
        >
          <ArrowLeft className="h-4 w-4 text-danger" />
          Jump to the {flags.length} flagged payee{flags.length === 1 ? "" : "s"}
        </button>
      )}
    </div>
  );
}
