/**
 * μ-law @ 8kHz ↔ PCM16 @ 24kHz conversion for the Twilio bridge.
 * Implemented from G.711 reference tables; no external deps.
 */

const MU = 255;
const BIAS = 0x84;

export function muLawDecodeByte(byte: number): number {
  byte = ~byte & 0xff;
  const sign = byte & 0x80;
  const exponent = (byte >> 4) & 0x07;
  const mantissa = byte & 0x0f;
  let sample = ((mantissa << 3) + BIAS) << exponent;
  sample -= BIAS;
  return sign ? -sample : sample;
}

export function muLawEncodeSample(sample: number): number {
  const sign = sample < 0 ? 0x80 : 0x00;
  if (sample < 0) sample = -sample;
  if (sample > 32635) sample = 32635;
  sample += BIAS;
  let exponent = 7;
  for (let mask = 0x4000; (sample & mask) === 0 && exponent > 0; mask >>= 1) exponent--;
  const mantissa = (sample >> (exponent + 3)) & 0x0f;
  return ~(sign | (exponent << 4) | mantissa) & 0xff;
}

export function muLawToPcm16(buf: Buffer): Int16Array {
  const out = new Int16Array(buf.length);
  for (let i = 0; i < buf.length; i++) out[i] = muLawDecodeByte(buf[i]!);
  return out;
}

export function pcm16ToMuLaw(samples: Int16Array): Buffer {
  const out = Buffer.alloc(samples.length);
  for (let i = 0; i < samples.length; i++) out[i] = muLawEncodeSample(samples[i]!);
  return out;
}

/**
 * Linear-interpolation resample. Adequate for 8 kHz ↔ 24 kHz on speech;
 * not a generalized DSP filter — Twilio audio is already band-limited.
 */
export function resamplePcm16(input: Int16Array, fromHz: number, toHz: number): Int16Array {
  if (fromHz === toHz) return input;
  const ratio = fromHz / toHz;
  const outLen = Math.floor(input.length / ratio);
  const out = new Int16Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const src = i * ratio;
    const lo = Math.floor(src);
    const hi = Math.min(lo + 1, input.length - 1);
    const frac = src - lo;
    out[i] = Math.round(input[lo]! * (1 - frac) + input[hi]! * frac);
  }
  return out;
}

export function pcm16ToBase64(pcm: Int16Array): string {
  const buf = Buffer.from(pcm.buffer, pcm.byteOffset, pcm.byteLength);
  return buf.toString('base64');
}

export function base64ToPcm16(b64: string): Int16Array {
  const buf = Buffer.from(b64, 'base64');
  return new Int16Array(buf.buffer, buf.byteOffset, buf.length / 2);
}
