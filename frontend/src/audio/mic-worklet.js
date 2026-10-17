// Captures mono microphone audio at the context sample rate and posts ~20 ms Float32 chunks.
class MicCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.chunk = new Float32Array(Math.round(sampleRate * 0.02));
    this.filled = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input.length) return true;
    const channel = input[0];
    let i = 0;
    while (i < channel.length) {
      const n = Math.min(channel.length - i, this.chunk.length - this.filled);
      this.chunk.set(channel.subarray(i, i + n), this.filled);
      this.filled += n;
      i += n;
      if (this.filled === this.chunk.length) {
        this.port.postMessage(this.chunk, [this.chunk.buffer]);
        this.chunk = new Float32Array(this.chunk.length);
        this.filled = 0;
      }
    }
    return true;
  }
}

registerProcessor("mic-capture", MicCaptureProcessor);
