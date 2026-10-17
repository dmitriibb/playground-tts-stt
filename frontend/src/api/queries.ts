import { useQuery } from "@tanstack/react-query";
import { api } from "./client";
import type { Fixture, Health, ModelInfo } from "./types";

export const useModels = () =>
  useQuery({ queryKey: ["models"], queryFn: () => api<ModelInfo[]>("/api/models"), staleTime: 30_000 });

export const useHealth = () =>
  useQuery({
    queryKey: ["health"],
    queryFn: () => api<Health>("/api/health", { quiet: true }),
    refetchInterval: 5000,
    retry: false,
  });

export const useFixtures = () =>
  useQuery({ queryKey: ["fixtures"], queryFn: () => api<Fixture[]>("/api/fixtures"), staleTime: 60_000 });

/** Loaded models that can serve a task (used by the STT/TTS row model pickers). */
export function useLoadedModels(task: "stt" | "tts"): ModelInfo[] {
  const { data } = useModels();
  return (data ?? []).filter((m) => m.task === task && m.state.load === "loaded");
}
