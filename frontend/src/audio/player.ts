import { int16ToFloat } from "./pcm";

/** Plays streamed PCM chunks gaplessly and reports when sound actually starts. */
export class PcmPlayer {
  private constructor(
    private ctx: AudioContext,
    private node: AudioWorkletNode,
  ) {}

  onStarted?: (perfNow: number) => void;
  onEnded?: () => void;

  static async create(sampleRate: number): Promise<PcmPlayer> {
    const ctx = new AudioContext({ sampleRate });
    await ctx.audioWorklet.addModule(new URL("./player-worklet.js", import.meta.url));
    const node = new AudioWorkletNode(ctx, "pcm-player", { outputChannelCount: [1] });
    node.connect(ctx.destination);
    const player = new PcmPlayer(ctx, node);
    node.port.onmessage = (e: MessageEvent<{ type: string }>) => {
      if (e.data.type === "started") {
        // The block was rendered now; it reaches the speakers after the output latency.
        const latencyMs = ((ctx.outputLatency || 0) + (ctx.baseLatency || 0)) * 1000;
        player.onStarted?.(performance.now() + latencyMs);
      } else if (e.data.type === "ended") player.onEnded?.();
    };
    if (ctx.state === "suspended") await ctx.resume();
    return player;
  }

  push(pcm: Int16Array): void {
    const f = int16ToFloat(pcm);
    this.node.port.postMessage(f, [f.buffer]);
  }

  end(): void {
    this.node.port.postMessage("end");
  }

  async close(): Promise<void> {
    this.node.port.postMessage("clear");
    this.node.disconnect();
    if (this.ctx.state !== "closed") await this.ctx.close();
  }
}
