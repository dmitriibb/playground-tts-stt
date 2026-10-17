import type { QueryClient } from "@tanstack/react-query";
import { create } from "zustand";
import { wsUrl } from "../config";
import { reportError } from "../store/errors";
import type { BusEvent } from "./protocol";
import type { ModelInfo } from "./types";

interface EventsState {
  connected: boolean;
  setConnected: (v: boolean) => void;
}

export const useEventsStatus = create<EventsState>((set) => ({
  connected: false,
  setConnected: (connected) => set({ connected }),
}));

/** Subscribe to /ws/events: keeps the model list fresh and feeds the error panel. Reconnects. */
export function connectEvents(queryClient: QueryClient): () => void {
  let ws: WebSocket | null = null;
  let stopped = false;
  let retry: ReturnType<typeof setTimeout> | undefined;

  const updateModel = (model: ModelInfo) => {
    queryClient.setQueryData<ModelInfo[]>(["models"], (old) =>
      old ? old.map((m) => (m.id === model.id ? model : m)) : old,
    );
  };

  const open = () => {
    ws = new WebSocket(wsUrl("/ws/events"));
    ws.onopen = () => {
      useEventsStatus.getState().setConnected(true);
      queryClient.invalidateQueries({ queryKey: ["models"] });
    };
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data as string) as BusEvent;
      if (msg.type === "model.state") updateModel(msg.data.model);
      else if (msg.type === "download.progress") {
        queryClient.setQueryData<ModelInfo[]>(["models"], (old) =>
          old?.map((m) =>
            m.id === msg.data.model_id
              ? {
                  ...m,
                  state: {
                    ...m.state,
                    download: "downloading",
                    download_progress: msg.data.progress,
                    downloaded_mb: msg.data.downloaded_mb,
                  },
                }
              : m,
          ),
        );
      } else if (msg.type === "log") {
        const d = msg.data;
        reportError({
          ts: msg.ts * 1000,
          level: d.level === "warning" ? "warning" : "error",
          source: msg.source,
          code: d.code,
          message: d.message,
          requestId: d.request_id,
          sessionId: d.session_id,
          modelId: d.model_id,
          traceback: d.traceback,
          details: d.details,
        });
      }
    };
    ws.onclose = () => {
      useEventsStatus.getState().setConnected(false);
      if (!stopped) retry = setTimeout(open, 2000);
    };
  };

  open();
  return () => {
    stopped = true;
    clearTimeout(retry);
    ws?.close();
  };
}
