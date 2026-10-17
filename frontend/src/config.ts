/** Backend location comes from `.env` (VITE_API_URL), so one frontend build can target any backend. */
export const API_URL: string = (import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

export function wsUrl(path: string, base: string = API_URL): string {
  const url = new URL(path, base + "/");
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}
