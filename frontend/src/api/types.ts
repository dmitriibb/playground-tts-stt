/** Friendly aliases over the types generated from the backend OpenAPI schema (npm run gen:api). */
import type { components } from "./schema";

type S = components["schemas"];

export type ModelInfo = S["ModelInfo"];
export type ModelState = S["ModelState"];
export type RunnerState = S["RunnerState"];
export type RunnerConfig = S["RunnerConfig"];
export type Voice = S["Voice"];
export type ServerTimings = S["ServerTimings"];
export type TranscribeResult = S["TranscribeResult"];
export type BatchResult = S["BatchResult"];
export type SynthesizeResult = S["SynthesizeResult"];
export type Fixture = S["Fixture"];
export type Device = "cpu" | "gpu";

export interface ErrorBody {
  code: string;
  message: string;
  details?: Record<string, unknown>;
  request_id?: string | null;
}

export interface Health {
  status: string;
  version: string;
  protocol: number;
  models_dir: string;
  loaded_models: string[];
  system: {
    python: string;
    platform: string;
    cpu: { name: string; physical_cores: number; logical_cores: number; ram_total_mb: number };
    gpus: string[];
    runtimes: Record<string, Record<string, unknown> | null>;
  } | null;
}

export const STT_MODES = [
  "file_single",
  "file_batch",
  "live_endpointed",
  "live_windowed",
  "live_native",
  "live_batched",
  "file_chunked",
] as const;
export type SttMode = (typeof STT_MODES)[number];

export const TTS_MODES = ["tts_file", "tts_stream", "tts_batch"] as const;
export type TtsMode = (typeof TTS_MODES)[number];
