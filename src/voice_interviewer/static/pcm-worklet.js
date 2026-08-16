class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.targetRate = 16000;
    this.pending = new Float32Array(0);
    this.offset = 0;
  }

  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input?.length) return true;

    const combined = new Float32Array(this.pending.length + input.length);
    combined.set(this.pending);
    combined.set(input, this.pending.length);

    const ratio = sampleRate / this.targetRate;
    const output = [];
    let position = this.offset;
    while (position + 1 < combined.length) {
      const left = Math.floor(position);
      const fraction = position - left;
      output.push(combined[left] * (1 - fraction) + combined[left + 1] * fraction);
      position += ratio;
    }

    const consumed = Math.floor(position);
    this.pending = combined.slice(consumed);
    this.offset = position - consumed;

    if (output.length) {
      const pcm = new Int16Array(output.length);
      for (let index = 0; index < output.length; index += 1) {
        const sample = Math.max(-1, Math.min(1, output[index]));
        pcm[index] = sample < 0 ? sample * 32768 : sample * 32767;
      }
      this.port.postMessage(pcm.buffer, [pcm.buffer]);
    }
    return true;
  }
}

registerProcessor("pcm-capture", PcmCaptureProcessor);
