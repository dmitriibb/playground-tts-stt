import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../api/client";
import { type TtsServerMessage, unpackFrame } from "../../api/protocol";
import type { ServerTimings, SynthesizeResult } from "../../api/types";
import { PcmPlayer } from "../../audio/player";
import { concatInt16, encodeWav } from "../../audio/wav";
import { wsUrl } from "../../config";
import { reportError } from "../../store/errors";
import type { TtsRowConfig } from "./store";

export interface TtsRunState {
  status: "idle" | "waiting" | "streaming" | "playing" | "done" | "error" | "cancelled";
  firstChunkMs?: number; // client: request sent -> first audio bytes received
  firstPlayedMs?: number; // client: request sent -> first sample rendered by the audio device
  totalMs?: number; // client: request sent -> last audio received
  audioMs?: number;
  segments: { text: string; audioMs: number; timings: ServerTimings }[];
  server?: Partial<ServerTimings>;
  streamMetrics?: Record<string, unknown>;
  streamingKind?: string;
  wav?: Blob;
  error?: string;
}

const initial: TtsRunState = { status: "idle", segments: [] };

function b64ToBlob(b64: string): Blob {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type: "audio/wav" });
}

export function useTtsRun(cfg: TtsRowConfig) {
  const [state, setState] = useState<TtsRunState>(initial);
  const cfgRef = useRef(cfg);
  cfgRef.current = cfg;
  const wsRef = useRef<WebSocket | null>(null);
  const playerRef = useRef<PcmPlayer | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const stopAudio = () => {
    playerRef.current?.close();
    playerRef.current = null;
    audioRef.current?.pause();
    audioRef.current = null;
  };

  const fail = (message: string, code?: string) =>
    setState((s) => ({ ...s, status: "error", error: code ? `${code}: ${message}` : message }));

  const runFile = async () => {
    const c = cfgRef.current;
    const t0 = performance.now();
    setState({ ...initial, status: "waiting" });
    const res = await api<SynthesizeResult>("/api/tts/synthesize", {
      method: "POST",
      body: JSON.stringify({ model_id: c.modelId, text: c.text, voice: c.voice || null, language: c.language, speed: c.speed }),
    });
    const received = performance.now() - t0;
    const wav = b64ToBlob(res.audio_wav_b64);
    const audio = new Audio(URL.createObjectURL(wav));
    audioRef.current = audio;
    audio.onplaying = () => setState((s) => ({ ...s, firstPlayedMs: s.firstPlayedMs ?? performance.now() - t0 }));
    audio.onended = () => setState((s) => ({ ...s, status: "done" }));
    setState((s) => ({
      ...s,
      status: "playing",
      firstChunkMs: received,
      totalMs: received,
      audioMs: res.audio_duration_ms,
      server: res.timings,
      wav,
      streamingKind: "whole file",
    }));
    await audio.play();
  };

  const runStream = () =>
    new Promise<void>((resolve) => {
      const c = cfgRef.current;
      setState({ ...initial, status: "waiting" });
      const ws = new WebSocket(wsUrl("/ws/tts"));
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;
      let t0 = 0;
      let sampleRate = 24000;
      const chunks: Int16Array[] = [];
      let playerReady: Promise<PcmPlayer> | null = null;
      ws.onopen = () => {
        t0 = performance.now();
        ws.send(JSON.stringify({ type: "start", model_id: c.modelId, text: c.text, voice: c.voice || null, language: c.language, speed: c.speed }));
      };
      ws.onmessage = async (ev) => {
        if (typeof ev.data !== "string") {
          const { pcm } = unpackFrame(ev.data as ArrayBuffer);
          const now = performance.now() - t0;
          chunks.push(pcm);
          setState((s) => ({ ...s, status: "streaming", firstChunkMs: s.firstChunkMs ?? now, totalMs: now }));
          (await playerReady)?.push(pcm);
          return;
        }
        const msg = JSON.parse(ev.data) as TtsServerMessage;
        if (msg.type === "audio.meta") {
          sampleRate = msg.sample_rate;
          setState((s) => ({ ...s, streamingKind: msg.streaming_kind }));
          playerReady = PcmPlayer.create(sampleRate).then((p) => {
            playerRef.current = p;
            p.onStarted = (at) => setState((s) => ({ ...s, firstPlayedMs: s.firstPlayedMs ?? at - t0 }));
            p.onEnded = () => setState((s) => ({ ...s, status: s.status === "playing" ? "done" : s.status }));
            return p;
          });
        } else if (msg.type === "segment") {
          setState((s) => ({ ...s, segments: [...s.segments, { text: msg.text, audioMs: msg.audio_ms, timings: msg.timings }], server: msg.timings }));
        } else if (msg.type === "done") {
          const pcm = concatInt16(chunks);
          setState((s) => ({
            ...s,
            status: "playing",
            audioMs: (pcm.length / sampleRate) * 1000,
            streamMetrics: msg.metrics,
            wav: encodeWav(pcm, sampleRate),
          }));
          (await playerReady)?.end();
          ws.close();
          resolve();
        } else if (msg.type === "error") {
          reportError({
            level: "error",
            source: "tts",
            code: msg.error.code,
            message: msg.error.message,
            requestId: msg.error.request_id,
            modelId: c.modelId,
          });
          fail(msg.error.message, msg.error.code);
          ws.close();
          resolve();
        }
      };
      ws.onerror = () => {
        reportError({ level: "error", source: "client", message: `Cannot connect to ${wsUrl("/ws/tts")}` });
        fail("WebSocket error");
        resolve();
      };
    });

  const runBatch = async () => {
    const c = cfgRef.current;
    const t0 = performance.now();
    setState({ ...initial, status: "waiting" });
    const res = await api<{ items: { audio_wav_b64?: string; error?: { code: string; message: string } }[]; timings: ServerTimings }>(
      "/api/tts/batch",
      { method: "POST", body: JSON.stringify({ model_id: c.modelId, items: [{ text: c.text, voice: c.voice || null, language: c.language, speed: c.speed }] }) },
    );
    const ms = performance.now() - t0;
    const first = res.items[0];
    if (first?.error) return fail(first.error.message, first.error.code);
    setState((s) => ({ ...s, status: "done", firstChunkMs: ms, totalMs: ms, server: res.timings, wav: first?.audio_wav_b64 ? b64ToBlob(first.audio_wav_b64) : undefined }));
  };

  const run = useCallback(async () => {
    const c = cfgRef.current;
    if (!c.modelId) return fail("Select a loaded model");
    if (!c.text.trim()) return fail("Enter some text");
    stopAudio();
    try {
      if (c.mode === "tts_stream") await runStream();
      else if (c.mode === "tts_batch") await runBatch();
      else await runFile();
    } catch (e) {
      if (e instanceof ApiError) fail(e.body.message, e.body.code);
      else fail((e as Error).message);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const cancel = useCallback(() => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "cancel" }));
    ws?.close();
    stopAudio();
    setState((s) => ({ ...s, status: "cancelled" }));
  }, []);

  useEffect(() => () => {
    wsRef.current?.close();
    stopAudio();
  }, []);

  return { state, run, cancel, clear: () => setState(initial) };
}
