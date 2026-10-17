import { floatToInt16, Framer, rms, StreamResampler } from "./pcm";

export const TARGET_RATE = 16000;

/**
 * Microphone -> AudioWorklet -> resample to 16 kHz -> Int16 frames of `frameMs`.
 * Works on http://localhost; other origins need HTTPS for getUserMedia.
 */
export class MicCapture {
  private constructor(
    private ctx: AudioContext,
    private stream: MediaStream,
    private node: AudioWorkletNode,
    private framer: Framer,
    private onFrame: (pcm: Int16Array) => void,
  ) {}

  static async start(opts: {
    frameMs: number;
    onFrame: (pcm: Int16Array) => void;
    onLevel?: (level: number) => void;
  }): Promise<MicCapture> {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    const ctx = new AudioContext();
    await ctx.audioWorklet.addModule(new URL("./mic-worklet.js", import.meta.url));
    const source = ctx.createMediaStreamSource(stream);
    const node = new AudioWorkletNode(ctx, "mic-capture");
    const resampler = new StreamResampler(ctx.sampleRate, TARGET_RATE);
    const framer = new Framer(Math.round((TARGET_RATE * opts.frameMs) / 1000));
    node.port.onmessage = (e: MessageEvent<Float32Array>) => {
      opts.onLevel?.(rms(e.data));
      for (const frame of framer.push(floatToInt16(resampler.push(e.data)))) opts.onFrame(frame);
    };
    source.connect(node);
    return new MicCapture(ctx, stream, node, framer, opts.onFrame);
  }

  /** Stop capturing; the last partial frame is delivered before this resolves. */
  async stop(): Promise<void> {
    this.node.port.onmessage = null;
    const rest = this.framer.flush();
    if (rest) this.onFrame(rest);
    this.stream.getTracks().forEach((t) => t.stop());
    this.node.disconnect();
    await this.ctx.close();
  }
}
