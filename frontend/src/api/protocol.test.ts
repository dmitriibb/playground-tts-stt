import { beforeEach, describe, expect, it } from "vitest";
import { wsUrl } from "../config";
import { useErrors } from "../store/errors";
import { packFrame, unpackFrame } from "./protocol";

describe("protocol", () => {
  it("packs a 4-byte little-endian seq before the PCM", () => {
    const frame = packFrame(258, new Int16Array([1, -2, 3]));
    const bytes = new Uint8Array(frame);
    expect(Array.from(bytes.slice(0, 4))).toEqual([2, 1, 0, 0]);
    const { seq, pcm } = unpackFrame(frame);
    expect(seq).toBe(258);
    expect(Array.from(pcm)).toEqual([1, -2, 3]);
  });

  it("derives ws urls from the API url", () => {
    expect(wsUrl("/ws/stt", "http://host:8000")).toBe("ws://host:8000/ws/stt");
    expect(wsUrl("/ws/tts", "https://example.com/base")).toBe("wss://example.com/ws/tts");
  });
});

describe("error store", () => {
  beforeEach(() => useErrors.getState().clear());

  it("merges the HTTP error and the server log event of the same request", () => {
    const { add } = useErrors.getState();
    add({ level: "error", source: "client", code: "INFERENCE_FAILED", message: "boom", requestId: "r1" });
    add({ level: "error", source: "tts", code: "INFERENCE_FAILED", message: "boom", requestId: "r1", traceback: "Traceback…" });
    add({ level: "error", source: "stt", code: "QUEUE_FULL", message: "full", requestId: "r2" });
    const { entries, unread } = useErrors.getState();
    expect(entries).toHaveLength(2);
    expect(unread).toBe(2);
    const merged = entries.find((e) => e.requestId === "r1")!;
    expect(merged.traceback).toBe("Traceback…");
    expect(merged.source).toBe("tts");
  });

  it("keeps entries without request ids separate", () => {
    const { add } = useErrors.getState();
    add({ level: "warning", source: "gateway", message: "a" });
    add({ level: "warning", source: "gateway", message: "a" });
    expect(useErrors.getState().entries).toHaveLength(2);
  });
});
