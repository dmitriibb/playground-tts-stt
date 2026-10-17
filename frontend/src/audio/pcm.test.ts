import { describe, expect, it } from "vitest";
import { floatToInt16, Framer, int16ToFloat, StreamResampler } from "./pcm";
import { encodeWav } from "./wav";

describe("pcm", () => {
  it("converts float <-> int16", () => {
    const f = new Float32Array([0, 0.5, -0.5, 1, -1, 2]);
    const i = floatToInt16(f);
    expect(Array.from(i)).toEqual([0, 16384, -16384, 32767, -32768, 32767]);
    expect(int16ToFloat(i)[1]).toBeCloseTo(0.5, 3);
  });

  it("resamples 48k -> 16k with the right length across chunk boundaries", () => {
    const r = new StreamResampler(48000, 16000);
    let total = 0;
    for (let k = 0; k < 50; k++) total += r.push(new Float32Array(960).fill(0.25)).length; // 50 x 20 ms
    expect(Math.abs(total - 16000)).toBeLessThanOrEqual(3);
  });

  it("keeps a DC level and a low tone intact", () => {
    const r = new StreamResampler(44100, 16000);
    const out = r.push(new Float32Array(44100).fill(0.5));
    expect(out[100]).toBeCloseTo(0.5, 5);
    const tone = new Float32Array(48000).map((_, i) => Math.sin((2 * Math.PI * 200 * i) / 48000));
    const res = new StreamResampler(48000, 16000).push(tone);
    const peak = Math.max(...Array.from(res.slice(100, 15000)));
    expect(peak).toBeGreaterThan(0.95);
  });

  it("upsamples by interpolation", () => {
    const out = new StreamResampler(8000, 16000).push(new Float32Array([0, 1, 0, 1, 0, 1, 0, 1]));
    expect(out.length).toBeGreaterThanOrEqual(12);
    expect(out[1]).toBeCloseTo(0.5, 5);
  });

  it("frames samples and flushes the rest", () => {
    const f = new Framer(640);
    expect(f.push(new Int16Array(1000)).length).toBe(1);
    expect(f.push(new Int16Array(300)).length).toBe(1);
    expect(f.flush()?.length).toBe(20);
    expect(f.flush()).toBeNull();
  });

  it("writes a valid WAV header", async () => {
    const blob = encodeWav(new Int16Array(160), 16000);
    const buf = new Uint8Array(await blob.arrayBuffer());
    expect(buf.length).toBe(44 + 320);
    expect(String.fromCharCode(...buf.slice(0, 4))).toBe("RIFF");
    expect(new DataView(buf.buffer).getUint32(24, true)).toBe(16000);
  });
});
