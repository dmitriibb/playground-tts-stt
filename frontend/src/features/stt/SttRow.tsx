import { useEffect, useRef, useState } from "react";
import { useFixtures, useLoadedModels } from "../../api/queries";
import type { ModelInfo, SttMode } from "../../api/types";
import { Badge, Button, Card, cn, Field, fmtMs, Input, Metric, Segmented, Select } from "../../components/ui";
import { newRowId, type SttRowConfig, useSttRows } from "./store";
import { useSttRun } from "./useSttRun";

const MODE_OPTIONS: { value: SttMode; label: string }[] = [
  { value: "file_single", label: "File" },
  { value: "file_batch", label: "Batch" },
  { value: "live_endpointed", label: "Live · endpointed" },
  { value: "live_windowed", label: "Live · windowed" },
  { value: "live_native", label: "Live · native" },
];

const LANGS = [
  { value: "en", label: "EN" },
  { value: "ru", label: "RU" },
  { value: "de", label: "DE" },
  { value: "", label: "auto" },
];

export function SttRow({ cfg, index }: { cfg: SttRowConfig; index: number }) {
  const { update, remove, clone, runTick } = useSttRows();
  const models = useLoadedModels("stt");
  const fixtures = useFixtures().data ?? [];
  const { state, level, run, micStart, micStop, cancel, clear } = useSttRun(cfg);
  const [showEvents, setShowEvents] = useState(false);
  const set = (patch: Partial<SttRowConfig>) => update(cfg.id, patch);
  const model: ModelInfo | undefined = models.find((m) => m.id === cfg.modelId);

  // Keep the selection valid as models get loaded/unloaded.
  useEffect(() => {
    if (!model && models.length) set({ modelId: models[0].id });
    if (model && !model.modes[cfg.mode]) {
      const first = MODE_OPTIONS.find((o) => model.modes[o.value]);
      if (first) set({ mode: first.value });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model?.id, models.length]);

  useEffect(() => {
    if (!cfg.fixtureIds.length && fixtures.length) {
      const f = fixtures.find((x) => x.language === (cfg.language || "en")) ?? fixtures[0];
      set({ fixtureIds: [f.id] });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fixtures.length]);

  // "Run all rows" starts every row at the same moment (mic rows are skipped).
  const tick = useRef(runTick);
  useEffect(() => {
    if (runTick !== tick.current) {
      tick.current = runTick;
      if (cfg.source !== "mic") run();
    }
  }, [runTick, cfg.source, run]);

  const live = cfg.mode.startsWith("live_");
  const busy = ["connecting", "recording", "streaming", "waiting"].includes(state.status);
  const micActive = state.status === "recording" || (state.status === "streaming" && cfg.source === "mic");

  const micHandlers =
    cfg.micMode === "hold"
      ? { onPointerDown: micStart, onPointerUp: micStop, onPointerLeave: () => micActive && micStop() }
      : { onClick: () => (micActive ? micStop() : micStart()) };

  return (
    <Card className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(380px,440px)_1fr]">
      {/* ---------------- controls ---------------- */}
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

        <Segmented<SttMode>
          value={cfg.mode}
          onChange={(mode) => set({ mode })}
          options={MODE_OPTIONS.map((o) => ({
            ...o,
            disabled: !model?.modes[o.value],
            hint: model?.mode_notes?.[o.value] ?? (model?.modes[o.value] ? undefined : "Not supported by this model"),
          }))}
        />
        {model?.mode_notes?.[cfg.mode] && <div className="text-[11px] text-zinc-500">{model.mode_notes[cfg.mode]}</div>}

        <div className="flex flex-wrap items-end gap-2">
          <Field label="Language">
            <Segmented value={cfg.language} onChange={(language) => set({ language })} options={LANGS} />
          </Field>
          <Field label="Source">
            <Segmented
              value={cfg.source}
              onChange={(source) => set({ source })}
              options={[
                { value: "fixture", label: "Fixture" },
                { value: "file", label: "File" },
                { value: "mic", label: "Mic" },
              ]}
            />
          </Field>
          <Field label="Beam">
            <Input type="number" min={1} max={10} value={cfg.beamSize} onChange={(e) => set({ beamSize: +e.target.value })} className="w-14" />
          </Field>
        </div>

        {cfg.source === "fixture" && (
          <Field label={cfg.mode === "file_batch" ? "Fixtures (ctrl/shift-click for several)" : "Fixture"}>
            <Select
              multiple={cfg.mode === "file_batch"}
              value={cfg.mode === "file_batch" ? cfg.fixtureIds : (cfg.fixtureIds[0] ?? "")}
              onChange={(e) => set({ fixtureIds: Array.from(e.target.selectedOptions, (o) => o.value) })}
              className={cn(cfg.mode === "file_batch" && "h-28")}
            >
              {fixtures.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.id} {f.duration_ms ? `(${(f.duration_ms / 1000).toFixed(1)} s)` : ""}
                </option>
              ))}
            </Select>
          </Field>
        )}
        {cfg.source === "file" && (
          <input
            type="file"
            accept="audio/*"
            multiple={cfg.mode === "file_batch"}
            onChange={(e) => set({ files: Array.from(e.target.files ?? []) })}
            className="block w-full text-xs text-zinc-400 file:mr-2 file:rounded file:border-0 file:bg-zinc-800 file:px-2 file:py-1 file:text-zinc-200"
          />
        )}

        {live && (
          <div className="flex flex-wrap items-end gap-2 rounded-md bg-zinc-950/60 p-2">
            <Field label="Frame ms">
              <Input type="number" min={10} max={1000} step={10} value={cfg.frameMs} onChange={(e) => set({ frameMs: +e.target.value })} className="w-16" />
            </Field>
            {cfg.source !== "mic" && (
              <label className="flex items-center gap-1 pb-1.5 text-xs text-zinc-400" title="Send the file at real-time pace, like a microphone">
                <input type="checkbox" checked={cfg.realtime} onChange={(e) => set({ realtime: e.target.checked })} /> real-time pace
              </label>
            )}
            {cfg.mode === "live_endpointed" && (
              <>
                <Field label="Silence ms" hint="Silence that ends an utterance">
                  <Input type="number" value={cfg.vad.silence_ms} onChange={(e) => set({ vad: { ...cfg.vad, silence_ms: +e.target.value } })} className="w-16" />
                </Field>
                <Field label="VAD thr.">
                  <Input type="number" step={0.05} value={cfg.vad.threshold} onChange={(e) => set({ vad: { ...cfg.vad, threshold: +e.target.value } })} className="w-16" />
                </Field>
                <Field label="Pre-roll ms">
                  <Input type="number" value={cfg.vad.pre_roll_ms} onChange={(e) => set({ vad: { ...cfg.vad, pre_roll_ms: +e.target.value } })} className="w-16" />
                </Field>
                <Field label="Partial every ms" hint="Re-transcribe the open utterance for partials (0 = off)">
                  <Input type="number" value={cfg.vad.partial_interval_ms} onChange={(e) => set({ vad: { ...cfg.vad, partial_interval_ms: +e.target.value } })} className="w-20" />
                </Field>
              </>
            )}
            {cfg.mode === "live_windowed" && (
              <>
                <Field label="Window ms">
                  <Input type="number" value={cfg.window.size_ms} onChange={(e) => set({ window: { ...cfg.window, size_ms: +e.target.value } })} className="w-20" />
                </Field>
                <Field label="Stride ms">
                  <Input type="number" value={cfg.window.stride_ms} onChange={(e) => set({ window: { ...cfg.window, stride_ms: +e.target.value } })} className="w-20" />
                </Field>
                <Field label="Tail ms" hint="Recent audio that is never committed">
                  <Input type="number" value={cfg.window.tail_ms} onChange={(e) => set({ window: { ...cfg.window, tail_ms: +e.target.value } })} className="w-20" />
                </Field>
              </>
            )}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2 border-t border-zinc-800 pt-2.5">
          {cfg.source === "mic" ? (
            <>
              <Button variant={micActive ? "danger" : "primary"} className="touch-none" disabled={!model} {...micHandlers}>
                🎙 {cfg.micMode === "hold" ? (micActive ? "Release to stop" : "Hold to talk") : micActive ? "Stop" : "Start mic"}
              </Button>
              <Segmented value={cfg.micMode} onChange={(micMode) => set({ micMode })} options={[{ value: "hold", label: "hold" }, { value: "toggle", label: "toggle" }]} />
              <div className="h-2 w-20 overflow-hidden rounded bg-zinc-800" title="input level">
                <div className="h-full bg-emerald-500" style={{ width: `${Math.min(100, level * 400)}%` }} />
              </div>
            </>
          ) : (
            <Button variant="primary" disabled={!model || busy} onClick={run}>
              ▶ Send
            </Button>
          )}
          <Button variant="outline" disabled={!busy} onClick={cancel}>
            Cancel
          </Button>
          <div className="ml-auto flex gap-1">
            <Button size="sm" variant="ghost" onClick={clear} title="Clear result">
              Clear
            </Button>
            <Button size="sm" variant="ghost" onClick={() => clone(cfg.id, 1, newRowId)} title="Duplicate row">
              Duplicate
            </Button>
            <Button size="sm" variant="ghost" className="text-red-400" onClick={() => remove(cfg.id)}>
              Remove
            </Button>
          </div>
        </div>
      </div>

      {/* ---------------- result + metrics ---------------- */}
      <div className="flex min-w-0 flex-col gap-2">
        <div className="flex items-center gap-2 text-xs">
          <StatusBadge status={state.status} />
          {state.sessionId && <span className="font-mono text-zinc-500">session {state.sessionId}</span>}
          {state.error && <span className="truncate text-red-400">{state.error}</span>}
        </div>
        <div className="min-h-24 flex-1 rounded-md border border-zinc-800 bg-zinc-950 p-2 text-sm leading-relaxed">
          {state.finals.map((f, i) => (
            <span key={i} className="text-zinc-100">
              {f.label && <span className="mr-1 font-mono text-[10px] text-sky-400">[{f.label}]</span>}
              {f.text}{" "}
              {state.finals.length > 1 && cfg.mode === "file_batch" && <br />}
            </span>
          ))}
          {state.partial && <span className="italic text-zinc-500">{state.partial}</span>}
          {!state.finals.length && !state.partial && <span className="text-zinc-600">Result appears here as pieces arrive…</span>}
        </div>

        <div className="grid grid-cols-3 gap-2 rounded-md bg-zinc-950/60 p-2 sm:grid-cols-6">
          <Metric label="→ first partial" value={fmtMs(state.firstPartialMs)} hint="From the first audio sent to the first partial (or result)" />
          <Metric label="→ first final" value={fmtMs(state.firstFinalMs)} hint="From the first audio sent to the first final text" />
          <Metric label="→ completed" value={fmtMs(state.completedMs)} hint="From the first audio sent to session/response end" />
          <Metric
            label="end → done"
            value={fmtMs(state.endInputMs !== undefined && state.completedMs !== undefined ? state.completedMs - state.endInputMs : undefined)}
            hint="From end_input to session.completed (finalization latency)"
          />
          <Metric label="queue wait" value={fmtMs(state.server?.queue_wait_ms)} hint="Server: time waiting for a worker (last request)" />
          <Metric label="compute" value={fmtMs(state.server?.compute_ms)} hint="Server: inference time (last request)" />
          <Metric
            label="batch"
            value={state.server?.batch_size ? `×${state.server.batch_size}${state.server.batch_id ? ` #${state.server.batch_id}` : ""}` : "—"}
            hint="Size and id of the server batch the last request ran in"
          />
          <Metric label="RTF" value={state.server?.rtf != null ? state.server.rtf.toFixed(3) : "—"} hint="Compute time / audio duration" />
          <Metric label="device" value={state.server?.device ?? "—"} />
          <Metric label="audio sent" value={live ? fmtMs(state.audioSentMs) : fmtMs(state.server?.audio_duration_ms)} />
          <Metric label="frames" value={live ? state.framesSent : "—"} />
          <Metric label="finals" value={state.finals.length} />
        </div>

        <button className="self-start text-[11px] text-zinc-500 hover:text-zinc-300" onClick={() => setShowEvents(!showEvents)}>
          {showEvents ? "▾" : "▸"} timeline ({state.events.length} events)
        </button>
        {showEvents && (
          <div className="max-h-40 overflow-y-auto rounded bg-zinc-950 p-2 font-mono text-[11px] text-zinc-400">
            {state.events.map((e, i) => (
              <div key={i}>
                <span className="inline-block w-20 text-right text-zinc-500">{Math.round(e.t)} ms</span>{" "}
                <span className="text-zinc-200">{e.kind}</span> {e.detail}
              </div>
            ))}
            {state.sessionMetrics && <pre className="mt-1 text-zinc-500">{JSON.stringify(state.sessionMetrics, null, 1)}</pre>}
          </div>
        )}
      </div>
    </Card>
  );
}

function StatusBadge({ status }: { status: string }) {
  const tone = status === "done" ? "green" : status === "error" ? "red" : status === "idle" || status === "cancelled" ? "zinc" : "amber";
  return <Badge tone={tone}>{status}</Badge>;
}
