import React, { useEffect, useState } from "react";
import { Share2, AlertCircle, RefreshCw } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { getApiUrl } from "../services/apiConfig";

interface Edge {
  user: string;
  merchant: string;
}

interface Node {
  id: string;
  type: "user" | "merchant";
  degree: number;
}

export default function NetworkGraph() {
  const { token } = useAuth();
  const [edges, setEdges] = useState<Edge[]>([]);
  const [nodes, setNodes] = useState<Node[]>([]);
  const [suspiciousNodes, setSuspiciousNodes] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const headers = { Authorization: `Bearer ${token}` };
      const [edgesRes, gnnRes] = await Promise.all([
        fetch(getApiUrl("/api/fraud-graph"), { headers }),
        fetch(getApiUrl("/api/gnn-fraud-detection"), { headers })
      ]);

      if (!edgesRes.ok || !gnnRes.ok) {
        throw new Error("Unable to retrieve graph telemetry");
      }

      const edgesData = await edgesRes.json();
      const gnnData = await gnnRes.json();

      const fetchedEdges: Edge[] = edgesData.edges || [];
      setEdges(fetchedEdges);
      setSuspiciousNodes(gnnData.suspicious_nodes || []);

      // Derive nodes and degrees
      const nodeMap: Record<string, { type: "user" | "merchant"; degree: number }> = {};
      fetchedEdges.forEach(e => {
        if (!nodeMap[e.user]) {
          nodeMap[e.user] = { type: "user", degree: 0 };
        }
        nodeMap[e.user].degree++;

        if (!nodeMap[e.merchant]) {
          nodeMap[e.merchant] = { type: "merchant", degree: 0 };
        }
        nodeMap[e.merchant].degree++;
      });

      const derivedNodes: Node[] = Object.entries(nodeMap).map(([id, info]) => ({
        id,
        type: info.type,
        degree: info.degree,
      }));
      setNodes(derivedNodes);
    } catch (err: any) {
      setError(err.message || "Failed to load network metadata");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  // Compute node coordinates in SVG space (circular/distributed layout)
  const layoutNodes = () => {
    const width = 800;
    const height = 500;
    const centerX = width / 2;
    const centerY = height / 2;
    const radius = 180;

    const coords: Record<string, { x: number; y: number }> = {};

    nodes.forEach((n, idx) => {
      // Alternate radius to spread users and merchants
      const r = n.type === "merchant" ? radius * 0.7 : radius * 1.1;
      const angle = (idx / nodes.length) * 2 * Math.PI;
      coords[n.id] = {
        x: centerX + r * Math.cos(angle),
        y: centerY + r * Math.sin(angle),
      };
    });

    return coords;
  };

  const coords = layoutNodes();

  return (
    <div className="space-y-8 animate-fade-in" id="network-graph-container">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-white mb-2">Fraud Network Graph</h1>
          <p className="text-slate-400">
            Real-time link-analysis visualization representing connection paths between users and UPI payment terminals.
          </p>
        </div>

        <button
          onClick={fetchData}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 bg-slate-900 hover:bg-slate-800 text-slate-300 font-medium rounded-lg border border-slate-800 transition shadow-sm h-fit self-start md:self-auto"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Reload Graph Data
        </button>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-4 gap-8">
        {/* Left Stats Column */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-6 xl:col-span-1">
          <h3 className="font-semibold text-white">Network Telemetry</h3>

          <div className="space-y-4">
            <div className="p-3 bg-slate-950 rounded-lg">
              <span className="text-xs text-slate-500 block uppercase font-semibold">Total Nodes</span>
              <span className="text-3xl font-extrabold text-white mt-1 block">{nodes.length}</span>
            </div>

            <div className="p-3 bg-slate-950 rounded-lg">
              <span className="text-xs text-slate-500 block uppercase font-semibold">Connection Links</span>
              <span className="text-3xl font-extrabold text-white mt-1 block">{edges.length}</span>
            </div>

            <div className="p-3 bg-rose-500/10 border border-rose-500/20 text-rose-400 rounded-lg">
              <span className="text-xs text-rose-500 block uppercase font-semibold">GNN Suspicious Flagged</span>
              <span className="text-3xl font-extrabold text-rose-300 mt-1 block">{suspiciousNodes.length}</span>
            </div>
          </div>

          <div className="pt-4 border-t border-slate-800 text-xs space-y-2 text-slate-400">
            <div className="flex items-center gap-2">
              <div className="w-3.5 h-3.5 bg-indigo-500 rounded-full shrink-0" />
              <span>User Node (UPI Sender)</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3.5 h-3.5 bg-emerald-500 rounded-md shrink-0" />
              <span>Merchant / Terminal Node</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3.5 h-3.5 bg-rose-500 rounded-full border-2 border-white shrink-0 animate-pulse" />
              <span>Suspicious Node (degree &ge; 3)</span>
            </div>
          </div>
        </div>

        {/* Dynamic Graph Visualizer SVG */}
        <div className="xl:col-span-3 bg-slate-950 border border-slate-900 rounded-xl overflow-hidden relative min-h-[500px]">
          {loading ? (
            <div className="absolute inset-0 flex items-center justify-center bg-slate-950/80 z-10">
              <div className="h-10 w-10 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : error ? (
            <div className="absolute inset-0 flex flex-col items-center justify-center p-6 text-center">
              <AlertCircle className="h-12 w-12 text-rose-500 mb-2" />
              <p className="text-slate-400">{error}</p>
            </div>
          ) : nodes.length === 0 ? (
            <div className="absolute inset-0 flex flex-col items-center justify-center p-6 text-center">
              <Share2 className="h-12 w-12 text-slate-700 mb-2" />
              <p className="text-slate-400">No network data active. Run some transactions in the risk prediction panel first!</p>
            </div>
          ) : (
            <svg
              viewBox="0 0 800 500"
              className="w-full h-full select-none"
              id="svg-network-canvas"
            >
              {/* Connection Edges */}
              <g id="edges-group">
                {edges.map((e, idx) => {
                  const p1 = coords[e.user];
                  const p2 = coords[e.merchant];
                  if (!p1 || !p2) return null;

                  const isSuspicious = suspiciousNodes.includes(e.user) || suspiciousNodes.includes(e.merchant);

                  return (
                    <line
                      key={idx}
                      x1={p1.x}
                      y1={p1.y}
                      x2={p2.x}
                      y2={p2.y}
                      stroke={isSuspicious ? "#f43f5e" : "#334155"}
                      strokeWidth={isSuspicious ? 2.5 : 1.5}
                      strokeDasharray={isSuspicious ? "5,5" : undefined}
                      opacity={isSuspicious ? 1 : 0.6}
                    />
                  );
                })}
              </g>

              {/* Nodes and Labels */}
              <g id="nodes-group">
                {nodes.map((node) => {
                  const pos = coords[node.id];
                  if (!pos) return null;

                  const isSuspicious = suspiciousNodes.includes(node.id);

                  return (
                    <g key={node.id} transform={`translate(${pos.x}, ${pos.y})`}>
                      {node.type === "user" ? (
                        <circle
                          r={isSuspicious ? 14 : 10}
                          fill={isSuspicious ? "#f43f5e" : "#6366f1"}
                          stroke={isSuspicious ? "#ffffff" : "#4f46e5"}
                          strokeWidth={2}
                          className="transition-all hover:scale-125 duration-150"
                        />
                      ) : (
                        <rect
                          x={isSuspicious ? -12 : -9}
                          y={isSuspicious ? -12 : -9}
                          width={isSuspicious ? 24 : 18}
                          height={isSuspicious ? 24 : 18}
                          rx={3}
                          fill={isSuspicious ? "#f43f5e" : "#10b981"}
                          stroke={isSuspicious ? "#ffffff" : "#059669"}
                          strokeWidth={2}
                          className="transition-all hover:scale-125 duration-150"
                        />
                      )}
                      
                      {/* Suspicious halo pulsing */}
                      {isSuspicious && (
                        <circle
                          r={24}
                          fill="transparent"
                          stroke="#f43f5e"
                          strokeWidth={1.5}
                          className="animate-ping"
                          opacity={0.4}
                        />
                      )}

                      {/* Text Label */}
                      <text
                        y={24}
                        textAnchor="middle"
                        fill="#f1f5f9"
                        fontSize={10}
                        fontWeight="semibold"
                        className="font-sans pointer-events-none drop-shadow"
                      >
                        {node.id}
                      </text>
                    </g>
                  );
                })}
              </g>
            </svg>
          )}
        </div>
      </div>
    </div>
  );
}
