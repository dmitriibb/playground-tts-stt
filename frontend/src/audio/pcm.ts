export function floatToInt16(input: Float32Array): Int16Array {
  const out = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]));
    out[i] = s < 0 ? Math.round(s * 32768) : Math.round(s * 32767);
  }
  return out;
}

export function int16ToFloat(input: Int16Array): Float32Array {
  const out = new Float32Array(input.length);
  for (let i = 0; i < input.length; i++) out[i] = input[i] / 32768;
  return out;
}

export function rms(input: Float32Array): number {
  if (!input.length) return 0;
  let sum = 0;
  for (let i = 0; i < input.length; i++) sum += input[i] * input[i];
  return Math.sqrt(sum / input.length);
}

/**
 * Streaming resampler. Downsampling averages the input samples around each output position
 * (box filter, enough anti-aliasing for speech), upsampling interpolates linearly. State is
 * kept between `push` calls so chunk boundaries don't click.
 */
export class StreamResampler {
  private readonly ratio: number;
  private buf = new Float32Array(0);
  private pos = 0; // position of the next output sample, in `buf` coordinates

  constructor(
    readonly inRate: number,
    readonly outRate: number,
  ) {
    this.ratio = inRate / outRate;
  }

  push(input: Float32Array): Float32Array {
    if (this.inRate === this.outRate) return input.slice();
    const merged = new Float32Array(this.buf.length + input.length);
    merged.set(this.buf);
    merged.set(input, this.buf.length);
    const half = this.ratio > 1 ? this.ratio / 2 : 0;
    const out: number[] = [];
    while (this.pos + half + 1 < merged.length) {
      if (this.ratio > 1) {
        const start = Math.max(0, Math.ceil(this.pos - half));
        const end = Math.min(merged.length - 1, Math.floor(this.pos + half));
        let sum = 0;
        for (let i = start; i <= end; i++) sum += merged[i];
        out.push(sum / (end - start + 1));
      } else {
        const i = Math.floor(this.pos);
        const frac = this.pos - i;
        out.push(merged[i] * (1 - frac) + merged[i + 1] * frac);
      }
      this.pos += this.ratio;
    }
    const keepFrom = Math.max(0, Math.floor(this.pos - half) - 1);
    this.buf = merged.slice(keepFrom);
    this.pos -= keepFrom;
    return Float32Array.from(out);
  }
}

/** Collects samples and emits fixed-size frames. */
export class Framer {
  private pending: Int16Array = new Int16Array(0);

  constructor(readonly frameSamples: number) {}

  push(samples: Int16Array): Int16Array[] {
    const merged = new Int16Array(this.pending.length + samples.length);
    merged.set(this.pending);
    merged.set(samples, this.pending.length);
    const frames: Int16Array[] = [];
    let i = 0;
    for (; i + this.frameSamples <= merged.length; i += this.frameSamples) {
      frames.push(merged.slice(i, i + this.frameSamples));
    }
    this.pending = merged.slice(i);
    return frames;
  }

  flush(): Int16Array | null {
    if (!this.pending.length) return null;
    const rest = this.pending;
    this.pending = new Int16Array(0);
    return rest;
  }
}
