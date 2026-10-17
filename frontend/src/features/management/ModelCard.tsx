import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, json } from "../../api/client";
import type { Device, ModelInfo, RunnerConfig } from "../../api/types";
import { Badge, Button, Card, Dialog, Field, fmtMb, fmtMs, Input, Progress, Segmented } from "../../components/ui";

const MODE_LABELS: Record<string, string> = {
  file_single: "file",
  file_batch: "batch",
  live_native: "native stream",
  live_windowed: "windowed",
  live_endpointed: "endpointed",
  live_batched: "multi-stream batch",
  file_chunked: "chunked",
  tts_file: "file",
  tts_stream: "stream",
  tts_batch: "batch",
};

export function ModelCard({ model: m }: { model: ModelInfo }) {
  const qc = useQueryClient();
  const s = m.state;
  const [device, setDevice] = useState<Device>((s.device as Device) ?? "cpu");
  const [threads, setThreads] = useState(0);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const update = (info: ModelInfo) =>
    qc.setQueryData<ModelInfo[]>(["models"], (old) => old?.map((x) => (x.id === info.id ? info : x)));
  const action = useMutation({
    mutationFn: (req: { path: string; method: string; body?: unknown }) =>
      api<ModelInfo>(`/api/models/${m.id}${req.path}`, {
        method: req.method,
        body: req.body ? json(req.body) : undefined,
      }),
    onSuccess: update,
  });

  const downloaded = s.download === "downloaded";
  const loaded = s.load === "loaded";
  const busy = action.isPending || s.load === "loading" || s.load === "unloading" || s.download === "downloading";
  const gpuNow = m.devices_available_now.includes("gpu");

  return (
    <Card className="space-y-2.5">
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-zinc-100">{m.name}</span>
            <StateBadge model={m} />
          </div>
          <div className="mt-0.5 font-mono text-[11px] text-zinc-500">
            {m.id} · {m.engine} {m.engine_version ?? "(not installed)"}
          </div>
        </div>
      </div>

      {!m.engine_available && <div className="rounded bg-amber-950/60 px-2 py-1 text-xs text-amber-300">{m.unavailable_reason}</div>}

      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
        <Info k="Params" v={m.params ?? "—"} />
        <Info k="Disk" v={fmtMb(m.disk_size_mb)} />
        <Info k="Est. RAM" v={fmtMb(m.est_ram_mb)} />
        <Info k="Est. VRAM" v={fmtMb(m.est_vram_mb)} />
      </div>

      <div className="flex flex-wrap items-center gap-1">
        <span className="mr-1 text-[11px] text-zinc-500">Languages</span>
        {m.languages.map((l) => (
          <Badge key={l}>{l}</Badge>
        ))}
        {m.voices && (
          <details className="ml-2 text-[11px] text-zinc-400">
            <summary className="cursor-pointer">{m.voices.length} voice(s)</summary>
            <div className="mt-1 flex flex-wrap gap-1">
              {m.voices.map((v) => (
                <Badge key={v.id} title={`${v.language} ${v.gender ?? ""}`}>
                  {v.name} · {v.language}
                </Badge>
              ))}
            </div>
          </details>
        )}
      </div>

      {Object.keys(m.modes).length > 0 && (
        <div className="flex flex-wrap items-center gap-1">
          <span className="mr-1 text-[11px] text-zinc-500">Capabilities</span>
          {Object.entries(m.modes).map(([mode, ok]) => (
            <Badge key={mode} tone={ok ? "sky" : "zinc"} title={m.mode_notes?.[mode]} className={ok ? "" : "line-through opacity-50"}>
              {MODE_LABELS[mode] ?? mode}
            </Badge>
          ))}
          {m.streaming_kind && <Badge tone="violet" title="How streaming really works">{m.streaming_kind}</Badge>}
          {m.native_batching && <Badge tone="violet">native batching</Badge>}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-1 text-[11px]">
        <span className="mr-1 text-zinc-500">Devices</span>
        {(["cpu", "gpu"] as Device[]).map((d) => (
          <Badge
            key={d}
            tone={m.devices_available_now.includes(d) ? "green" : "zinc"}
            title={d === "gpu" && !gpuNow ? (m.device_unavailable_reason ?? "unavailable") : undefined}
          >
            {d.toUpperCase()} {m.devices_available_now.includes(d) ? "✓" : "✕"}
          </Badge>
        ))}
        {!gpuNow && m.device_unavailable_reason && <span className="text-zinc-500">{m.device_unavailable_reason}</span>}
      </div>

      {(m.license || m.notes) && (
        <div className="text-[11px] text-zinc-500">
          {m.license && <span className="mr-2">License: {m.license}</span>}
          {m.license_note && <span className="mr-2 text-amber-400/80">{m.license_note}</span>}
          {m.notes}
        </div>
      )}

      <div className="text-[11px] text-zinc-500">
        Files: <span className="font-mono text-zinc-400">{s.path}</span>{" "}
        <button className="text-sky-400 hover:underline" onClick={() => navigator.clipboard.writeText(s.path)}>
          copy
        </button>
        <span className="ml-2">source: {m.source}</span>
      </div>

      {s.download === "downloading" && (
        <div className="space-y-1">
          <Progress value={s.download_progress} />
          <div className="text-[11px] text-zinc-400">
            Downloading… {Math.round(s.download_progress * 100)}% ({fmtMb(s.downloaded_mb)})
          </div>
        </div>
      )}
      {s.error && <div className="rounded bg-red-950/60 px-2 py-1 text-xs text-red-300">{s.error}</div>}

      <div className="flex flex-wrap items-end gap-2 border-t border-zinc-800 pt-2.5">
        {!downloaded && (
          <Button variant="primary" disabled={busy} onClick={() => action.mutate({ path: "/download", method: "POST" })}>
            {s.download === "downloading" ? "Downloading…" : "Download"}
          </Button>
        )}
        {downloaded && !loaded && (
          <>
            <Field label="Device">
              <Segmented<Device>
                value={device}
                onChange={setDevice}
                options={(["cpu", "gpu"] as Device[]).map((d) => ({
                  value: d,
                  label: d.toUpperCase(),
                  disabled: !m.devices_available_now.includes(d),
                  hint: d === "gpu" && !gpuNow ? (m.device_unavailable_reason ?? undefined) : undefined,
                }))}
              />
            </Field>
            <Field label="Threads" hint="Intra-op threads per request (0 = engine default)">
              <Input type="number" min={0} max={64} value={threads} onChange={(e) => setThreads(+e.target.value)} className="w-16" />
            </Field>
            <Button
              variant="primary"
              disabled={busy || !m.engine_available}
              onClick={() => action.mutate({ path: "/load", method: "POST", body: { device, threads } })}
            >
              {s.load === "loading" ? "Loading…" : "Load"}
            </Button>
          </>
        )}
        {loaded && (
          <Button disabled={busy} onClick={() => action.mutate({ path: "/unload", method: "POST" })}>
            {s.load === "unloading" ? "Unloading…" : "Unload"}
          </Button>
        )}
        {downloaded && (
          <Button variant="ghost" className="ml-auto text-red-400" disabled={busy || loaded} title={loaded ? "Unload first" : undefined} onClick={() => setConfirmDelete(true)}>
            Delete files
          </Button>
        )}
      </div>

      {loaded && <LoadedPanel model={m} onUpdate={update} />}

      <Dialog open={confirmDelete} onClose={() => setConfirmDelete(false)} title={`Delete ${m.name}?`}>
        <p className="mb-2 text-zinc-300">This removes the model files from the server disk:</p>
        <pre className="mb-3 overflow-x-auto rounded bg-zinc-950 p-2 font-mono text-xs text-zinc-300">{s.path}</pre>
        <p className="mb-4 text-xs text-zinc-500">{fmtMb(s.downloaded_mb)} will be freed. You can download it again later.</p>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => setConfirmDelete(false)}>
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={() => {
              setConfirmDelete(false);
              action.mutate({ path: "/files", method: "DELETE" });
            }}
          >
            Delete files
          </Button>
        </div>
      </Dialog>
    </Card>
  );
}

function StateBadge({ model: m }: { model: ModelInfo }) {
  const s = m.state;
  if (s.load === "loaded") return <Badge tone="green">loaded · {s.device?.toUpperCase()}</Badge>;
  if (s.load === "loading" || s.load === "unloading") return <Badge tone="amber">{s.load}…</Badge>;
  if (s.load === "error") return <Badge tone="red">load error</Badge>;
  if (s.download === "downloaded") return <Badge tone="sky">on disk · {fmtMb(s.downloaded_mb)}</Badge>;
  if (s.download === "downloading") return <Badge tone="amber">downloading</Badge>;
  if (s.download === "error") return <Badge tone="red">download error</Badge>;
  return <Badge>not downloaded</Badge>;
}

function Info({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <span className="text-zinc-500">{k}: </span>
      <span className="text-zinc-200">{v}</span>
    </div>
  );
}

const RUNNER_FIELDS: { key: keyof RunnerConfig; label: string; hint: string; batchOnly?: boolean }[] = [
  { key: "max_active", label: "Max active", hint: "Requests computed in parallel (worker threads)" },
  { key: "max_queued", label: "Queue size", hint: "Waiting requests before QUEUE_FULL" },
  { key: "max_batch_size", label: "Batch size", hint: "Dynamic batch across clients (native batching only)", batchOnly: true },
  { key: "max_wait_ms", label: "Batch wait ms", hint: "How long the first request waits for others to batch", batchOnly: true },
];

function LoadedPanel({ model: m, onUpdate }: { model: ModelInfo; onUpdate: (m: ModelInfo) => void }) {
  const s = m.state;
  const r = s.runner!;
  const [draft, setDraft] = useState<RunnerConfig>({
    max_active: r.max_active,
    max_queued: r.max_queued,
    max_batch_size: r.max_batch_size,
    max_wait_ms: r.max_wait_ms,
  });
  const dirty = RUNNER_FIELDS.some((f) => draft[f.key] !== r[f.key]);
  useEffect(() => {
    if (!dirty) setDraft({ max_active: r.max_active, max_queued: r.max_queued, max_batch_size: r.max_batch_size, max_wait_ms: r.max_wait_ms });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [r.max_active, r.max_queued, r.max_batch_size, r.max_wait_ms]);
  const patch = useMutation({
    mutationFn: () => api<ModelInfo>(`/api/models/${m.id}/runner`, { method: "PATCH", body: json(draft) }),
    onSuccess: onUpdate,
  });

  return (
    <div className="space-y-2 rounded-md bg-zinc-950/60 p-2 text-xs">
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-4">
        <Info k="Runtime" v={s.runtime ?? "—"} />
        <Info k="RAM (measured≈)" v={fmtMb(s.ram_mb)} />
        <Info k="VRAM (measured≈)" v={s.device === "gpu" ? fmtMb(s.vram_mb) : "—"} />
        <Info k="Load time" v={fmtMs(s.load_time_ms)} />
      </div>
      {m.task !== "vad" && (
        <>
          <div className="flex flex-wrap items-end gap-2">
            {RUNNER_FIELDS.filter((f) => !f.batchOnly || m.native_batching).map((f) => (
              <Field key={f.key} label={f.label} hint={f.hint}>
                <Input
                  type="number"
                  min={f.key === "max_active" || f.key === "max_batch_size" ? 1 : 0}
                  value={draft[f.key] ?? 0}
                  onChange={(e) => setDraft({ ...draft, [f.key]: +e.target.value })}
                  className="w-20"
                />
              </Field>
            ))}
            <Button size="sm" variant="primary" disabled={!dirty || patch.isPending} onClick={() => patch.mutate()}>
              Apply
            </Button>
          </div>
          <div className="flex flex-wrap gap-3 font-mono text-zinc-400">
            <span>active <b className="text-zinc-100">{r.active}</b></span>
            <span>queued <b className="text-zinc-100">{r.queued}</b></span>
            <span>done <b className="text-zinc-100">{r.completed}</b></span>
            <span>failed <b className={r.failed ? "text-red-400" : "text-zinc-100"}>{r.failed}</b></span>
            <span>rejected <b className={r.rejected ? "text-amber-400" : "text-zinc-100"}>{r.rejected}</b></span>
            <span>batches <b className="text-zinc-100">{r.batches}</b></span>
          </div>
        </>
      )}
    </div>
  );
}
