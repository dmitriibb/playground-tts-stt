import { useEventsStatus } from "../api/events";
import { useHealth } from "../api/queries";
import { API_URL } from "../config";
import { Badge, cn } from "./ui";

export type Tab = "management" | "tts" | "stt";

const TABS: { id: Tab; label: string }[] = [
  { id: "management", label: "Management" },
  { id: "tts", label: "TTS" },
  { id: "stt", label: "STT" },
];

export function Header({ tab, onTab }: { tab: Tab; onTab: (t: Tab) => void }) {
  const health = useHealth();
  const events = useEventsStatus((s) => s.connected);
  const ok = health.isSuccess && !health.isError;
  const sys = health.data?.system;
  const ort = sys?.runtimes?.onnxruntime as { gpu_provider?: string } | null | undefined;
  const title = sys
    ? `${sys.cpu.name} · ${sys.cpu.logical_cores} threads · ${Math.round(sys.cpu.ram_total_mb / 1024)} GB RAM\n` +
      `GPU: ${sys.gpus.join(", ") || "none"}\nONNX GPU provider: ${ort?.gpu_provider ?? "none"}\nPython ${sys.python}`
    : "backend unreachable";

  return (
    <header className="sticky top-0 z-10 flex h-12 items-center gap-6 border-b border-zinc-800 bg-zinc-950/95 px-4 backdrop-blur">
      <span className="text-sm font-semibold tracking-tight text-zinc-100">TTS / STT Playground</span>
      <nav className="flex gap-1">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => onTab(t.id)}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm",
              tab === t.id ? "bg-zinc-800 text-white" : "text-zinc-400 hover:text-zinc-200",
            )}
          >
            {t.label}
          </button>
        ))}
      </nav>
      <div className="ml-auto flex items-center gap-3 text-xs text-zinc-400" title={title}>
        {sys && (
          <span className="hidden text-zinc-500 lg:inline">
            {sys.gpus[0] ?? "no GPU"} · ORT GPU: {ort?.gpu_provider?.replace("ExecutionProvider", "") ?? "none"}
          </span>
        )}
        <span className="font-mono">{API_URL}</span>
        <span className="flex items-center gap-1.5">
          <span className={cn("h-2 w-2 rounded-full", ok ? "bg-emerald-400" : "bg-red-500")} />
          {ok ? `v${health.data?.version}` : "offline"}
        </span>
        <Badge tone={events ? "green" : "red"} title="/ws/events connection (errors + model state)">
          events {events ? "live" : "down"}
        </Badge>
      </div>
    </header>
  );
}
