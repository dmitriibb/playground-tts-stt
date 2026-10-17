import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../api/client";
import { packFrame, type JobTimings, type SttServerMessage } from "../../api/protocol";
import type { BatchResult, TranscribeResult } from "../../api/types";
import { MicCapture } from "../../audio/mic";
import { floatToInt16 } from "../../audio/pcm";
import { concatInt16, decodeToMono, encodeWav } from "../../audio/wav";
import { API_URL, wsUrl } from "../../config";
import { reportError } from "../../store/errors";
import type { SttRowConfig } from "./store";

export type RunStatus = "idle" | "connecting" | "recording" | "streaming" | "waiting" | "done" | "error" | "cancelled";

export interface TimelineEvent {
  t: number; // ms since the first audio was sent
  kind: string;
  detail?: string;
}

export interface SttRunState {
  status: RunStatus;
  finals: { text: string; startMs?: number; endMs?: number; label?: string }[];
  partial: string;
  events: TimelineEvent[];
  t0?: number; // performance.now() when the first audio left the client
  firstPartialMs?: number;
  firstFinalMs?: number;
  completedMs?: number;
  endInputMs?: number;
  framesSent: number;
  audioSentMs: number;
  server?: Partial<JobTimings> & { device?: string | null; rtf?: number | null; audio_duration_ms?: number | null };
  sessionMetrics?: Record<string, unknown>;
  error?: string;
  sessionId?: string;
}

const initial: SttRunState = { status: "idle", finals: [], partial: "", events: [], framesSent: 0, audioSentMs: 0 };
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function fetchFixture(id: string): Promise<{ name: string; data: ArrayBuffer }> {
  const res = await fetch(`${API_URL}/api/fixtures/${id}`);
  if (!res.ok) throw new Error(`Fixture ${id}: HTTP ${res.status}`);
  return { name: id.replace("/", "_"), data: await res.arrayBuffer() };
}

async function sourceFiles(cfg: SttRowConfig): Promise<{ name: string; data: ArrayBuffer }[]> {
  if (cfg.source === "fixture") return Promise.all(cfg.fixtureIds.map(fetchFixture));
  return Promise.all(cfg.files.map(async (f) => ({ name: f.name, data: await f.arrayBuffer() })));
}

/** One simulated client: drives file, batch and live modes for a row. */
export function useSttRun(cfg: SttRowConfig) {
  const [state, setState] = useState<SttRunState>(initial);
  const [level, setLevel] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const micRef = useRef<MicCapture | null>(null);
  const recordRef = useRef<Int16Array[]>([]);
  const seqRef = useRef(0);
  const t0Ref = useRef<number | undefined>(undefined);
  const cancelRef = useRef(false);
  const cfgRef = useRef(cfg);
  cfgRef.current = cfg;

  const since = () => (t0Ref.current === undefined ? 0 : performance.now() - t0Ref.current);
  const event = (kind: string, detail?: string) =>
    setState((s) => ({ ...s, events: [...s.events.slice(-300), { t: since(), kind, detail }] }));
  const markStart = () => {
    if (t0Ref.current === undefined) {
      t0Ref.current = performance.now();
      setState((s) => ({ ...s, t0: t0Ref.current }));
    }
  };
  const fail = (message: string, code?: string) => {
    setState((s) => ({ ...s, status: "error", error: code ? `${code}: ${message}` : message }));
  };

  const reset = (status: RunStatus) => {
    t0Ref.current = undefined;
    seqRef.current = 0;
    cancelRef.current = false;
    setState({ ...initial, status });
  };

  const closeWs = () => {
    const ws = wsRef.current;
    wsRef.current = null;
    if (ws && ws.readyState <= WebSocket.OPEN) ws.close();
  };

  // ---- file modes ---------------------------------------------------------------------

  const runFileSingle = async (file: { name: string; data: ArrayBuffer | Blob }) => {
    const c = cfgRef.current;
    const form = new FormData();
    form.append("file", file.data instanceof Blob ? file.data : new Blob([file.data]), file.name);
    form.append("options", JSON.stringify({ model_id: c.modelId, language: c.language || null, beam_size: c.beamSize }));
    setState((s) => ({ ...s, status: "waiting" }));
    markStart();
    event("request sent", file.name);
    const res = await api<TranscribeResult>("/api/stt/transcribe", { method: "POST", body: form });
    const ms = since();
    event("response", `${res.timings.batch_size > 1 ? `batch #${res.timings.batch_id} ×${res.timings.batch_size}` : "single"}`);
    setState((s) => ({
      ...s,
      status: "done",
      finals: [{ text: res.text, label: res.language ?? undefined }],
      firstFinalMs: ms,
      firstPartialMs: ms,
      completedMs: ms,
      server: res.timings,
    }));
  };

  const runFileBatch = async (files: { name: string; data: ArrayBuffer }[]) => {
    const c = cfgRef.current;
    const form = new FormData();
    for (const f of files) form.append("files", new Blob([f.data]), f.name);
    form.append("options", JSON.stringify({ model_id: c.modelId, language: c.language || null, beam_size: c.beamSize }));
    setState((s) => ({ ...s, status: "waiting" }));
    markStart();
    event("batch sent", `${files.length} files`);
    const res = await api<BatchResult>("/api/stt/batch", { method: "POST", body: form });
    const ms = since();
    setState((s) => ({
      ...s,
      status: "done",
      finals: res.items.map((i) => ({
        text: i.error ? `⚠ ${i.error.code}: ${i.error.message}` : (i.text ?? ""),
        label: i.filename,
      })),
      firstFinalMs: ms,
      completedMs: ms,
      server: res.timings,
    }));
  };

  // ---- live modes ---------------------------------------------------------------------

  const openLive = () =>
    new Promise<void>((resolve, reject) => {
      const c = cfgRef.current;
      const ws = new WebSocket(wsUrl("/ws/stt"));
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;
      let ready = false;
      ws.onopen = () =>
        ws.send(
          JSON.stringify({
            type: "start",
            model_id: c.modelId,
            mode: c.mode,
            language: c.language || null,
            frame_ms: c.frameMs,
            beam_size: c.beamSize,
            vad: c.vad,
            window: c.window,
          }),
        );
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data as string) as SttServerMessage;
        onLiveMessage(msg);
        if (msg.type === "ready") {
          ready = true;
          resolve();
        } else if (msg.type === "error" && !ready) reject(new ApiError(msg.error, 0));
      };
      ws.onerror = () => {
        if (!ready) reject(new Error(`Cannot connect to ${wsUrl("/ws/stt")}`));
      };
      ws.onclose = () => {
        setState((s) =>
          s.status === "streaming" || s.status === "waiting"
            ? { ...s, status: "error", error: s.error ?? "Connection closed before the session completed" }
            : s,
        );
      };
    });

  const onLiveMessage = (msg: SttServerMessage) => {
    const t = since();
    switch (msg.type) {
      case "ready":
        setState((s) => ({ ...s, sessionId: msg.session_id }));
        event("ready", `${msg.device} · session ${msg.session_id}`);
        break;
      case "vad":
        event(`vad ${msg.state}`, `@${Math.round(msg.at_ms)} ms audio`);
        break;
      case "transcript.partial":
        setState((s) => ({ ...s, partial: msg.text, firstPartialMs: s.firstPartialMs ?? t, server: { ...s.server, ...msg.timings } }));
        event("partial", `r${msg.revision}`);
        break;
      case "transcript.final":
        setState((s) => ({
          ...s,
          partial: "",
          finals: [...s.finals, { text: msg.text, startMs: msg.start_ms, endMs: msg.end_ms }],
          firstFinalMs: s.firstFinalMs ?? t,
          firstPartialMs: s.firstPartialMs ?? t,
          server: { ...s.server, ...msg.timings },
        }));
        event("final", msg.timings ? `batch ×${msg.timings.batch_size} · ${Math.round(msg.timings.compute_ms)} ms compute` : undefined);
        break;
      case "session.completed":
        setState((s) => ({
          ...s,
          status: "done",
          completedMs: t,
          sessionMetrics: msg.metrics,
          server: { ...s.server, device: msg.metrics.device as string, rtf: msg.metrics.rtf as number },
        }));
        event("completed");
        closeWs();
        break;
      case "cancelled":
        setState((s) => ({ ...s, status: "cancelled" }));
        break;
      case "error":
        reportError({
          level: "error",
          source: "stt",
          code: msg.error.code,
          message: msg.error.message,
          requestId: msg.error.request_id,
          sessionId: msg.error.request_id,
          modelId: cfgRef.current.modelId,
        });
        fail(msg.error.message, msg.error.code);
        event("error", msg.error.code);
        closeWs();
        break;
    }
  };

  const sendFrame = (pcm: Int16Array) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    markStart();
    ws.send(packFrame(seqRef.current++, pcm));
    const n = seqRef.current;
    setState((s) => ({ ...s, framesSent: n, audioSentMs: s.audioSentMs + (pcm.length / 16000) * 1000 }));
  };

  const endInput = () => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type: "end_input" }));
    setState((s) => ({ ...s, status: "waiting", endInputMs: since() }));
    event("end_input");
  };

  const streamFile = async (file: { name: string; data: ArrayBuffer }) => {
    const c = cfgRef.current;
    const audio = floatToInt16(await decodeToMono(file.data, 16000));
    await openLive();
    setState((s) => ({ ...s, status: "streaming" }));
    const step = Math.round((16000 * c.frameMs) / 1000);
    const start = performance.now();
    for (let i = 0, k = 0; i < audio.length; i += step, k++) {
      if (cancelRef.current || !wsRef.current) return;
      sendFrame(audio.subarray(i, i + step));
      if (c.realtime) {
        const wait = start + (k + 1) * c.frameMs - performance.now();
        if (wait > 0) await sleep(wait);
      } else if (k % 50 === 49) await sleep(0); // let the UI breathe
    }
    endInput();
  };

  // ---- public actions -------------------------------------------------------------------

  const run = useCallback(async () => {
    const c = cfgRef.current;
    if (!c.modelId) return fail("Select a loaded model");
    reset("connecting");
    try {
      if (c.source === "mic") return fail("Use the mic button for microphone input");
      const files = await sourceFiles(c);
      if (!files.length) return fail(c.source === "fixture" ? "Pick a fixture" : "Pick a file");
      if (c.mode === "file_single") await runFileSingle(files[0]);
      else if (c.mode === "file_batch") await runFileBatch(files);
      else await streamFile(files[0]);
    } catch (e) {
      if (e instanceof ApiError) fail(e.body.message, e.body.code);
      else {
        reportError({ level: "error", source: "client", message: (e as Error).message });
        fail((e as Error).message);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const micStart = useCallback(async () => {
    const c = cfgRef.current;
    if (!c.modelId) return fail("Select a loaded model");
    if (micRef.current) return;
    reset("connecting");
    recordRef.current = [];
    const live = c.mode.startsWith("live_");
    try {
      if (live) await openLive();
      micRef.current = await MicCapture.start({
        frameMs: c.frameMs,
        onLevel: setLevel,
        onFrame: (pcm) => (live ? sendFrame(pcm) : recordRef.current.push(pcm)),
      });
      setState((s) => ({ ...s, status: live ? "streaming" : "recording" }));
      event(live ? "mic streaming" : "mic recording");
    } catch (e) {
      closeWs();
      const msg = e instanceof ApiError ? e.body.message : (e as Error).message;
      if (!(e instanceof ApiError)) reportError({ level: "error", source: "client", message: `Microphone: ${msg}` });
      fail(msg, e instanceof ApiError ? e.body.code : undefined);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const micStop = useCallback(async () => {
    const mic = micRef.current;
    if (!mic) return;
    micRef.current = null;
    await mic.stop();
    setLevel(0);
    const c = cfgRef.current;
    if (c.mode.startsWith("live_")) return endInput();
    const pcm = concatInt16(recordRef.current);
    event("recorded", `${(pcm.length / 16000).toFixed(1)} s`);
    try {
      const wav = encodeWav(pcm, 16000);
      if (c.mode === "file_batch") await runFileBatch([{ name: "mic.wav", data: await wav.arrayBuffer() }]);
      else await runFileSingle({ name: "mic.wav", data: wav });
    } catch (e) {
      if (e instanceof ApiError) fail(e.body.message, e.body.code);
      else fail((e as Error).message);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const cancel = useCallback(() => {
    cancelRef.current = true;
    micRef.current?.stop();
    micRef.current = null;
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "cancel" }));
    closeWs();
    setState((s) => ({ ...s, status: "cancelled" }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(
    () => () => {
      cancelRef.current = true;
      micRef.current?.stop();
      wsRef.current?.close();
    },
    [],
  );

  return { state, level, run, micStart, micStop, cancel, clear: () => reset("idle") };
}
