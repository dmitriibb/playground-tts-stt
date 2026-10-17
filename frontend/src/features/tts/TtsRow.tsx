import { useEffect, useRef } from "react";
import { useLoadedModels } from "../../api/queries";
import type { TtsMode } from "../../api/types";
import { downloadBlob } from "../../audio/wav";
import { Badge, Button, Card, Field, fmtMs, Input, Metric, Segmented, Select, Textarea } from "../../components/ui";
import { newTtsRowId, PRESETS, type TtsRowConfig, useTtsRows } from "./store";
import { useTtsRun } from "./useTtsRun";

const MODES: { value: TtsMode; label: string }[] = [
  { value: "tts_file", label: "File" },
  { value: "tts_stream", label: "Stream" },
  { value: "tts_batch", label: "Batch" },
];

export function TtsRow({ cfg, index }: { cfg: TtsRowConfig; index: number }) {
  const { update, remove, clone, runTick } = useTtsRows();
  const models = useLoadedModels("tts");
  const { state, run, cancel, clear } = useTtsRun(cfg);
  const set = (patch: Partial<TtsRowConfig>) => update(cfg.id, patch);
  const model = models.find((m) => m.id === cfg.modelId);
  const voices = model?.voices ?? [];

  useEffect(() => {
    if (!model && models.length) set({ modelId: models[0].id });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model?.id, models.length]);
  useEffect(() => {
    if (!model) return;
    if (!voices.some((v) => v.id === cfg.voice)) set({ voice: voices[0]?.id ?? "" });
    if (!model.modes[cfg.mode]) set({ mode: MODES.find((m) => model.modes[m.value])?.value ?? "tts_file" });
    const lang = model.languages[0];
    if (lang && !model.languages.includes(cfg.language)) set({ language: lang, text: PRESETS[lang]?.medium ?? cfg.text });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model?.id]);

  const tick = useRef(runTick);
  useEffect(() => {
    if (runTick !== tick.current) {
      tick.current = runTick;
      run();
    }
  }, [runTick, run]);

  const busy = state.status === "waiting" || state.status === "streaming";
  const presets = PRESETS[cfg.language] ?? PRESETS.en;
  const finalizing = state.streamMetrics as Record<string, number> | undefined;

  return (
    <Card className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(380px,440px)_1fr]">
      <div className="space-y-2.5">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs text-zinc-500">#{index + 1}</span>
          <Select value={cfg.modelId} onChange={(e) => set({ modelId: e.target.value })} className="min-w-0 flex-1">
            {!models.length && <option value="">— load a model in Management —</option>}
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} · {m.state.device?.toUpperCase()}
              </option>
            ))}
          </Select>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Mode">
            <Segmented<TtsMode>
              value={cfg.mode}
              onChange={(mode) => set({ mode })}
              options={MODES.map((m) => ({
                ...m,
                disabled: !model?.modes[m.value],
                hint: model?.mode_notes?.[m.value] ?? (model?.modes[m.value] ? undefined : "Not supported by this model"),
              }))}
            />
          </Field>
          <Field label="Voice">
            <Select value={cfg.voice} onChange={(e) => set({ voice: e.target.value })} className="w-40">
              {voices.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name} · {v.language}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Speed">
            <Input type="number" min={0.5} max={2} step={0.1} value={cfg.speed} onChange={(e) => set({ speed: +e.target.value })} className="w-16" />
          </Field>
        </div>
        {cfg.mode === "tts_stream" && model?.streaming_kind && (
          <div className="text-[11px] text-zinc-500">
            <Badge tone="violet">{model.streaming_kind}</Badge> {model.mode_notes?.tts_stream}
          </div>
        )}
        <div className="flex flex-wrap items-center gap-1 text-xs">
          <span className="text-zinc-500">Presets</span>
          <Segmented
            value={cfg.language}
            onChange={(language) => set({ language, text: PRESETS[language].medium })}
            options={Object.keys(PRESETS).map((l) => ({ value: l, label: l.toUpperCase(), disabled: model ? !model.languages.includes(l) : false }))}
          />
          {(["short", "medium", "long"] as const).map((k) => (
            <Button key={k} size="sm" variant="ghost" onClick={() => set({ text: presets[k] })}>
              {k}
            </Button>
          ))}
        </div>
        <Textarea value={cfg.text} onChange={(e) => set({ text: e.target.value })} rows={4} className="w-full" />
        <div className="flex flex-wrap items-center gap-2 border-t border-zinc-800 pt-2.5">
          <Button variant="primary" disabled={!model || busy} onClick={run}>
            ▶ Generate
          </Button>
          <Button variant="outline" disabled={!busy && state.status !== "playing"} onClick={cancel}>
            Stop
          </Button>
          <Button variant="outline" disabled={!state.wav} onClick={() => state.wav && downloadBlob(state.wav, `${cfg.modelId}.wav`)}>
            ⬇ WAV
          </Button>
          <div className="ml-auto flex gap-1">
            <Button size="sm" variant="ghost" onClick={clear}>
              Clear
            </Button>
            <Button size="sm" variant="ghost" onClick={() => clone(cfg.id, 1, newTtsRowId)}>
              Duplicate
            </Button>
            <Button size="sm" variant="ghost" className="text-red-400" onClick={() => remove(cfg.id)}>
              Remove
            </Button>
          </div>
        </div>
      </div>

      <div className="flex min-w-0 flex-col gap-2">
        <div className="flex items-center gap-2 text-xs">
          <Badge tone={state.status === "done" ? "green" : state.status === "error" ? "red" : state.status === "idle" ? "zinc" : "amber"}>
            {state.status}
          </Badge>
          {state.streamingKind && <span className="text-zinc-500">{state.streamingKind}</span>}
          {state.error && <span className="truncate text-red-400">{state.error}</span>}
        </div>
        <div className="min-h-16 rounded-md border border-zinc-800 bg-zinc-950 p-2 text-xs text-zinc-400">
          {state.segments.length === 0 && <span className="text-zinc-600">Segments appear here as audio arrives…</span>}
          {state.segments.map((s, i) => (
            <div key={i} className="flex gap-2">
              <span className="w-14 shrink-0 text-right font-mono text-zinc-500">{fmtMs(s.audioMs)}</span>
              <span className="w-28 shrink-0 font-mono text-zinc-500">
                q {Math.round(s.timings.queue_wait_ms)} · c {Math.round(s.timings.compute_ms)}
              </span>
              <span className="text-zinc-300">{s.text}</span>
            </div>
          ))}
        </div>
        <div className="grid grid-cols-3 gap-2 rounded-md bg-zinc-950/60 p-2 sm:grid-cols-6">
          <Metric label="→ first chunk" value={fmtMs(state.firstChunkMs)} hint="Request sent → first audio bytes received" />
          <Metric label="→ first played" value={fmtMs(state.firstPlayedMs)} hint="Request sent → first sample rendered (incl. output latency)" />
          <Metric label="→ all audio" value={fmtMs(state.totalMs)} hint="Request sent → last audio received" />
          <Metric label="audio" value={fmtMs(state.audioMs)} />
          <Metric
            label="RTF"
            value={finalizing?.rtf != null ? Number(finalizing.rtf).toFixed(3) : state.server?.rtf != null ? state.server.rtf.toFixed(3) : "—"}
            hint="Server compute time / audio duration"
          />
          <Metric label="device" value={state.server?.device ?? "—"} />
          <Metric label="queue wait" value={fmtMs(finalizing?.queue_wait_ms_total ?? state.server?.queue_wait_ms)} hint="Server, summed over segments" />
          <Metric label="compute" value={fmtMs(finalizing?.compute_ms_total ?? state.server?.compute_ms)} hint="Server, summed over segments" />
          <Metric label="segments" value={state.segments.length || "—"} />
        </div>
      </div>
    </Card>
  );
}
