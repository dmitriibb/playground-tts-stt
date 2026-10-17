// Ring-buffer PCM player. Receives Float32 chunks; reports when the first sample is actually
// rendered ("started") and when the queue drained after the end of input ("ended").
class PcmPlayerProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.queue = [];
    this.offset = 0;
    this.started = false;
    this.inputEnded = false;
    this.endedSent = false;
    this.port.onmessage = (e) => {
      if (e.data === "end") this.inputEnded = true;
      else if (e.data === "clear") {
        this.queue = [];
        this.offset = 0;
      } else this.queue.push(e.data);
    };
  }

  process(_inputs, outputs) {
    const out = outputs[0][0];
    let written = 0;
    while (written < out.length && this.queue.length) {
      const head = this.queue[0];
      const n = Math.min(out.length - written, head.length - this.offset);
      out.set(head.subarray(this.offset, this.offset + n), written);
      written += n;
      this.offset += n;
      if (this.offset >= head.length) {
        this.queue.shift();
        this.offset = 0;
      }
    }
    for (let i = written; i < out.length; i++) out[i] = 0;
    if (written > 0 && !this.started) {
      this.started = true;
      this.port.postMessage({ type: "started", frame: currentFrame });
    }
    if (this.inputEnded && !this.queue.length && !this.endedSent) {
      this.endedSent = true;
      this.port.postMessage({ type: "ended" });
    }
    return true;
  }
}

registerProcessor("pcm-player", PcmPlayerProcessor);
