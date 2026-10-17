import { useModels } from "../../api/queries";
import { useHealth } from "../../api/queries";
import { ModelCard } from "./ModelCard";

export function ManagementTab() {
  const { data, isLoading, isError } = useModels();
  const health = useHealth();
  if (isLoading) return <div className="text-sm text-zinc-500">Loading models…</div>;
  if (isError || !data) return <div className="text-sm text-red-400">Cannot load models (see error panel).</div>;
  const tts = data.filter((m) => m.task === "tts");
  const stt = data.filter((m) => m.task === "stt" || m.task === "vad");
  return (
    <div className="space-y-3">
      <div className="text-xs text-zinc-500">
        Models directory on the server: <span className="font-mono text-zinc-300">{health.data?.models_dir ?? "…"}</span>
      </div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <section className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-400">TTS models</h2>
          {tts.map((m) => (
            <ModelCard key={m.id} model={m} />
          ))}
        </section>
        <section className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-400">STT models</h2>
          {stt.map((m) => (
            <ModelCard key={m.id} model={m} />
          ))}
        </section>
      </div>
    </div>
  );
}
