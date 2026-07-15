import axios from "axios";

// When empty (e.g. Docker deploy behind Nginx reverse-proxy), we use
// same-origin relative URLs. In the Emergent preview env, this is the
// preview URL injected at build time.
const BASE = process.env.REACT_APP_BACKEND_URL || "";
export const API_BASE = `${BASE}/api`;

export const api = axios.create({ baseURL: API_BASE });

api.interceptors.request.use((config) => {
  const t = localStorage.getItem("cema_token");
  if (t) config.headers.Authorization = `Bearer ${t}`;
  return config;
});

export function formatApiError(e) {
  const d = e?.response?.data?.detail;
  if (d == null) return e?.message || "Request failed";
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x?.msg || JSON.stringify(x)).join(" ");
  if (typeof d?.msg === "string") return d.msg;
  return String(d);
}

export function wsUrl(path) {
  if (BASE) {
    const u = new URL(BASE);
    u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
    return `${u.origin}${path}`;
  }
  // Same-origin fallback (Docker/reverse-proxy deploy)
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${path}`;
}
