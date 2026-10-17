/** WebSocket message shapes (protocol v0, see docs/PROTOCOL.md). */
import type { ErrorBody, ServerTimings } from "./types";

export interface JobTimings {
  queue_wait_ms: number;
  compute_ms: number;
  batch_id: number;
  batch_size: number;
}

export type SttServerMessage =
  | { type: "ready"; session_id: string; protocol: number; model_id: string; mode: string; device: string }
  | { type: "vad"; state: "speech_start" | "speech_end"; at_ms: number }
  | { type: "transcript.partial"; text: string; revision: number; at_ms: number; timings?: JobTimings }
  | {
      type: "transcript.final";
      text: string;
      start_ms: number;
      end_ms: number;
      at_ms: number;
      segment_index?: number;
      timings?: JobTimings;
    }
  | { type: "session.completed"; session_id: string; metrics: Record<string, unknown> }
  | { type: "cancelled"; session_id: string }
  | { type: "error"; error: ErrorBody };

export type TtsServerMessage =
  | {
      type: "audio.meta";
      session_id: string;
      sample_rate: number;
      format: "pcm_s16le";
      streaming_kind: string;
      segments: number;
      device: string;
    }
  | { type: "segment"; index: number; text: string; audio_ms: number; seq: number; timings: ServerTimings }
  | { type: "done"; session_id: string; metrics: Record<string, number | string | null> }
  | { type: "cancelled"; session_id: string }
  | { type: "error"; error: ErrorBody };

export type BusEvent =
  | { type: "hello"; protocol: number }
  | { type: "pong" }
  | { type: "model.state"; seq: number; ts: number; source: string; data: { model: import("./types").ModelInfo } }
  | {
      type: "download.progress";
      seq: number;
      ts: number;
      source: string;
      data: { model_id: string; progress: number; downloaded_mb: number; total_mb: number | null };
    }
  | {
      type: "log";
      seq: number;
      ts: number;
      source: string;
      data: {
        level: "error" | "warning";
        logger: string;
        message: string;
        code?: string;
        request_id?: string;
        session_id?: string;
        model_id?: string;
        traceback?: string;
        details?: unknown;
      };
    };

/** Binary frames carry a 4-byte little-endian sequence number before the PCM payload. */
export function packFrame(seq: number, pcm: Int16Array): ArrayBuffer {
  const out = new ArrayBuffer(4 + pcm.byteLength);
  new DataView(out).setUint32(0, seq, true);
  new Int16Array(out, 4).set(pcm);
  return out;
}

export function unpackFrame(data: ArrayBuffer): { seq: number; pcm: Int16Array } {
  const seq = new DataView(data).getUint32(0, true);
  const bytes = data.slice(4);
  return { seq, pcm: new Int16Array(bytes, 0, Math.floor(bytes.byteLength / 2)) };
}
