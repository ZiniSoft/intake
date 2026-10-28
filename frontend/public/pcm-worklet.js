// Converts the mixed meeting audio to 16-bit PCM and hands it to the page in ~250 ms frames.
// The AudioContext already runs at 16 kHz, so no resampling happens here.
class PcmCapture extends AudioWorkletProcessor {
  constructor() {
    super()
    this.frame = new Int16Array(4000)
    this.filled = 0
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0]
    if (!channel) return true
    for (let index = 0; index < channel.length; index += 1) {
      const sample = Math.max(-1, Math.min(1, channel[index]))
      this.frame[this.filled] = sample < 0 ? sample * 0x8000 : sample * 0x7fff
      this.filled += 1
      if (this.filled === this.frame.length) {
        const copy = this.frame.slice(0)
        this.port.postMessage(copy.buffer, [copy.buffer])
        this.filled = 0
      }
    }
    return true
  }
}

registerProcessor('pcm-capture', PcmCapture)
