import { useEffect, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { toast } from "sonner";
import { ScrollText } from "lucide-react";

const KIND_COLOR = {
  AUTH: "var(--accent-info)",
  DETECTION: "var(--accent-warning)",
  UPLOAD: "#FF8A00",
  CEMA: "var(--accent-info)",
  KILLCHAIN: "var(--accent-warning)",
  MAVLINK: "var(--accent-success)",
  PAYLOAD: "var(--accent-critical)",
  SYSTEM: "var(--text-muted)",
};

export default function MissionLog() {
  const [logs, setLogs] = useState([]);

  const load = async () => {
    try { const { data } = await api.get("/logs?limit=300"); setLogs(data); }
    catch (e) { toast.error("Load failed", { description: formatApiError(e) }); }
  };
  useEffect(() => { load(); const id = setInterval(load, 4000); return () => clearInterval(id); }, []);

  return (
    <div className="space-y-6">
      <div>
        <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mb-1">
          <ScrollText size={12} className="inline mr-2" strokeWidth={1.5} /> Mission Log
        </div>
        <h1 className="font-heading font-black text-5xl uppercase tracking-tighter">
          Audit Trail
        </h1>
      </div>

      <div className="tactical-border" style={{ background: "var(--bg-terminal)" }}>
        <div className="tactical-border-b px-4 py-3 flex items-center justify-between">
          <span className="font-mono text-xs uppercase tracking-widest" style={{ color: "var(--text-term)" }}>
            /var/log/cema-cuas.jsonl
          </span>
          <span className="font-mono text-[10px] text-slate-500 blink">● TAILING</span>
        </div>
        <div data-testid="mission-log-list" className="max-h-[70vh] overflow-y-auto font-mono text-xs">
          {logs.length === 0 && (
            <div className="p-4 text-slate-600">no events yet<span className="term-caret" /></div>
          )}
          {logs.map((l) => (
            <div key={l.id} data-testid={`log-${l.id}`}
                 className="px-4 py-2 tactical-border-b flex flex-col md:flex-row md:items-center gap-2 hover:bg-[#0F1626]">
              <span className="text-slate-500 shrink-0">{l.ts?.replace("T", " ").split(".")[0]}Z</span>
              <span className="uppercase tracking-widest text-[10px] shrink-0"
                    style={{ color: KIND_COLOR[l.kind] || "var(--text-primary)" }}>
                [{l.kind}]
              </span>
              <span className="text-slate-300 flex-1">{l.message}</span>
              <span className="text-slate-600 text-[10px]">{l.actor}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
