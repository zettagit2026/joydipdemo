import { useEffect, useMemo, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { toast } from "sonner";
import { Radar, Plus, Skull, Activity, Signal, TrendingUp } from "lucide-react";

const THREAT_COLOR = {
  LOW: "var(--accent-success)",
  MEDIUM: "var(--accent-warning)",
  HIGH: "#FF8A00",
  CRITICAL: "var(--accent-critical)",
};

function Waterfall() {
  const [rows, setRows] = useState([]);
  const [source, setSource] = useState("SIM");
  useEffect(() => {
    let id;
    const load = async () => {
      try {
        const { data } = await api.get("/spectrum/waterfall?bins=96&rows=24");
        setRows(data.rows);
        setSource(data.source || "SIM");
      } catch { /* silent */ }
    };
    load();
    id = setInterval(load, 2500);
    return () => clearInterval(id);
  }, []);

  const cell = (v) => {
    // v in dBm, range roughly -95..-30
    const norm = Math.min(1, Math.max(0, (v + 95) / 65));
    const hue = 200 - norm * 200; // cyan → red
    return `hsl(${hue}, 90%, ${20 + norm * 45}%)`;
  };

  const isReal = source === "HACKRF";

  return (
    <div data-testid="rf-waterfall" className="tactical-border" style={{ background: "var(--bg-terminal)" }}>
      <div className="flex items-center justify-between px-3 py-2 tactical-border-b">
        <div className="flex items-center gap-2">
          <Signal size={12} strokeWidth={1.5} style={{ color: "var(--accent-info)" }} />
          <span className="font-mono text-[10px] uppercase tracking-widest text-slate-400">
            RF Spectrum Waterfall · 2.400–2.500 GHz · 25 MSPS
          </span>
          <span
            data-testid="waterfall-source"
            className="px-2 py-0.5 font-mono text-[10px] font-bold uppercase tracking-widest tactical-border"
            style={{
              color: isReal ? "var(--accent-success)" : "var(--accent-warning)",
              borderColor: isReal ? "var(--accent-success)" : "var(--accent-warning)",
              background: isReal ? "rgba(57,255,20,0.08)" : "rgba(255,214,10,0.06)",
            }}
          >
            {isReal ? "● HACKRF LIVE" : "◌ SIM MODE"}
          </span>
        </div>
        <span className="font-mono text-[10px] text-slate-600 blink">● LIVE</span>
      </div>
      <div className="p-2">
        {rows.length === 0 && (
          <div className="font-mono text-xs text-slate-600 p-6 text-center">
            capturing IQ stream<span className="term-caret"></span>
          </div>
        )}
        {rows.map((row, ri) => (
          <div key={ri} className="flex" style={{ height: 8 }}>
            {row.map((v, ci) => (
              <div key={ci} className="wf-bar flex-1" style={{ background: cell(v) }} />
            ))}
          </div>
        ))}
      </div>
      <div className="tactical-border-t px-3 py-1 flex justify-between font-mono text-[10px] text-slate-600">
        <span>2.400</span><span>2.425</span><span>2.450</span><span>2.475</span><span>2.500 GHz</span>
      </div>
    </div>
  );
}

function StatTile({ label, value, sub, color = "var(--accent-info)", testid }) {
  return (
    <div data-testid={testid} className="tactical-border p-4" style={{ background: "var(--bg-surface)" }}>
      <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500">{label}</div>
      <div className="font-heading font-black text-4xl tracking-tighter mt-1" style={{ color }}>
        {value}
      </div>
      {sub && (
        <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mt-1">{sub}</div>
      )}
    </div>
  );
}

export default function Dashboard() {
  const [detections, setDetections] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      const { data } = await api.get("/detections");
      setDetections(data);
    } catch (e) {
      toast.error("Failed to load detections", { description: formatApiError(e) });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);

  const active = detections.filter((d) => d.status === "ACTIVE");
  const swarmCount = new Set(active.filter((d) => d.swarm_id).map((d) => d.swarm_id)).size;
  const critical = active.filter((d) => d.threat_level === "CRITICAL").length;
  const neutralized = detections.filter((d) => d.status === "NEUTRALIZED").length;
  // Any detection whose source is NOT the simulator counts as a live hardware feed.
  const liveSources = new Set(
    detections
      .map((d) => d.source)
      .filter((s) => s && s !== "SIM" && s !== "UPLOAD")
  );

  const simulate = async () => {
    try {
      await api.post("/detections/simulate");
      toast.success("New contact detected");
      load();
    } catch (e) {
      toast.error("Simulate failed", { description: formatApiError(e) });
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mb-1 flex items-center gap-3">
            <Radar size={12} className="inline" strokeWidth={1.5} /> Command Center
            {liveSources.size > 0 && (
              <span
                data-testid="live-hw-indicator"
                className="px-2 py-0.5 tactical-border font-mono text-[10px] font-bold"
                style={{
                  color: "var(--accent-success)",
                  borderColor: "var(--accent-success)",
                  background: "rgba(57,255,20,0.08)",
                }}
              >
                ● {Array.from(liveSources).join(" + ")} LIVE
              </span>
            )}
          </div>
          <h1 className="font-heading font-black text-5xl uppercase tracking-tighter">
            Tactical Overview
          </h1>
        </div>
        <button
          data-testid="simulate-detection-btn"
          onClick={simulate}
          title="Inject a fake contact for testing. Real detections come from HackRF / SiK radio."
          className="flex items-center gap-2 px-4 py-2 tactical-border font-mono text-xs uppercase tracking-widest hover:bg-white hover:text-black transition-colors scanline-btn"
        >
          <Plus size={14} strokeWidth={1.5} /> INJECT SIM
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-0 tactical-border">
        <div className="tactical-border-r">
          <StatTile testid="stat-active" label="Active Contacts" value={active.length} sub="Airspace targets" />
        </div>
        <div className="tactical-border-r">
          <StatTile testid="stat-critical" label="Critical Threats" value={critical}
                    color="var(--accent-critical)" sub="Immediate engagement" />
        </div>
        <div className="tactical-border-r">
          <StatTile testid="stat-swarms" label="Swarms Detected" value={swarmCount}
                    color="var(--accent-warning)" sub="Coordinated clusters" />
        </div>
        <StatTile testid="stat-neutralized" label="Neutralized" value={neutralized}
                  color="var(--accent-success)" sub="Kill-chain complete" />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className="xl:col-span-2 space-y-6">
          <Waterfall />

          <div className="tactical-border" style={{ background: "var(--bg-surface)" }}>
            <div className="tactical-border-b px-4 py-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Activity size={14} strokeWidth={1.5} style={{ color: "var(--accent-info)" }} />
                <span className="font-mono text-xs uppercase tracking-widest">Active Contacts</span>
              </div>
              <span className="font-mono text-[10px] text-slate-500">{active.length} tracked</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs" data-testid="detections-table">
                <thead>
                  <tr className="tactical-border-b font-mono text-[10px] uppercase tracking-widest text-slate-500">
                    <th className="text-left p-2">SRC</th>
                    <th className="text-left p-2">CALLSIGN</th>
                    <th className="text-left p-2">MODEL</th>
                    <th className="text-left p-2">PROTOCOL</th>
                    <th className="text-left p-2">THREAT</th>
                    <th className="text-right p-2">FREQ (GHz)</th>
                    <th className="text-right p-2">RSSI</th>
                    <th className="text-right p-2">DIST (m)</th>
                    <th className="text-left p-2">CEMA</th>
                    <th className="text-left p-2">KC</th>
                  </tr>
                </thead>
                <tbody className="font-mono">
                  {loading && (
                    <tr><td colSpan={10} className="p-4 text-center text-slate-500">acquiring<span className="term-caret" /></td></tr>
                  )}
                  {!loading && detections.length === 0 && (
                    <tr><td colSpan={10} className="p-4 text-center text-slate-500">No contacts. Trigger INJECT SIM or start the RF bridge.</td></tr>
                  )}
                  {detections.map((d) => {
                    const src = d.source || "SIM";
                    const isLive = src === "HACKRF" || src === "SIK_RADIO";
                    const srcColor = isLive ? "var(--accent-success)"
                                     : src === "UPLOAD" ? "var(--accent-warning)"
                                     : "var(--text-muted)";
                    return (
                      <tr key={d.id} data-testid={`row-${d.id}`}
                          className="tactical-border-b hover:bg-[#0F1626] transition-colors">
                        <td className="p-2">
                          <span data-testid={`src-${d.id}`}
                                className="px-1.5 py-0.5 tactical-border font-bold text-[9px]"
                                style={{ color: srcColor, borderColor: srcColor }}>
                            {src}
                          </span>
                        </td>
                        <td className="p-2 text-white">{d.callsign}</td>
                        <td className="p-2 text-slate-300">{d.model}</td>
                        <td className="p-2 text-slate-400">{d.protocol}</td>
                        <td className="p-2">
                          <span className="px-2 py-0.5 tactical-border font-bold text-[10px]"
                                style={{ color: THREAT_COLOR[d.threat_level], borderColor: THREAT_COLOR[d.threat_level] }}>
                            {d.threat_level}
                          </span>
                        </td>
                        <td className="p-2 text-right text-slate-300">{d.center_freq_ghz}</td>
                        <td className="p-2 text-right text-slate-300">{d.rssi_dbm}</td>
                        <td className="p-2 text-right text-slate-300">{d.distance_m}</td>
                        <td className="p-2 text-[10px]" style={{ color: "var(--accent-info)" }}>{d.cema_stage}</td>
                        <td className="p-2 text-[10px]"
                            style={{ color: d.status === "NEUTRALIZED" ? "var(--accent-critical)" : "var(--accent-success)" }}>
                          {d.status === "NEUTRALIZED" ? "DEFEAT" : d.kill_chain_stage}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="tactical-border" style={{ background: "var(--bg-surface)" }}>
          <div className="tactical-border-b px-4 py-3 flex items-center gap-2">
            <Skull size={14} strokeWidth={1.5} style={{ color: "var(--accent-critical)" }} />
            <span className="font-mono text-xs uppercase tracking-widest">Priority Targets</span>
          </div>
          <div className="p-4 space-y-3">
            {active
              .slice()
              .sort((a, b) => ({ CRITICAL: 3, HIGH: 2, MEDIUM: 1, LOW: 0 }[b.threat_level] - { CRITICAL: 3, HIGH: 2, MEDIUM: 1, LOW: 0 }[a.threat_level]))
              .slice(0, 6)
              .map((d) => (
                <div key={d.id} className="tactical-border p-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-mono text-xs text-white">{d.callsign}</span>
                    <span className="px-2 py-0.5 tactical-border font-mono font-bold text-[10px]"
                          style={{ color: THREAT_COLOR[d.threat_level], borderColor: THREAT_COLOR[d.threat_level] }}>
                      {d.threat_level}
                    </span>
                  </div>
                  <div className="font-mono text-[10px] text-slate-500 space-y-0.5">
                    <div>MODEL: <span className="text-slate-300">{d.model}</span></div>
                    <div>BEARING: <span className="text-slate-300">{d.bearing_deg}°</span> · ALT: <span className="text-slate-300">{d.altitude_m}m</span></div>
                    <div className="flex items-center gap-2">
                      <TrendingUp size={10} strokeWidth={1.5} /> {d.speed_ms} m/s
                      {d.swarm_id && (
                        <span className="ml-auto text-[10px]" style={{ color: "var(--accent-warning)" }}>{d.swarm_id}</span>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            {active.length === 0 && (
              <div className="font-mono text-xs text-slate-600 text-center py-4">— NO ACTIVE TARGETS —</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
