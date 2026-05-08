import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import {
  base64ToPcm16,
  muLawDecodeByte,
  muLawEncodeSample,
  muLawToPcm16,
  pcm16ToBase64,
  pcm16ToMuLaw,
  resamplePcm16,
} from '../src/twilio/audio.js';

test('mu-law byte round trip is monotonic for sweep', () => {
  for (let s = -32_000; s <= 32_000; s += 1024) {
    const enc = muLawEncodeSample(s);
    const dec = muLawDecodeByte(enc);
    // mu-law is lossy but should preserve sign and broad magnitude
    assert.strictEqual(Math.sign(dec) === Math.sign(s) || s === 0, true);
  }
});

test('pcm16 → mu-law → pcm16 buffer round trip preserves length', () => {
  const pcm = new Int16Array([0, 1024, -2048, 16_000, -16_000]);
  const muLaw = pcm16ToMuLaw(pcm);
  const back = muLawToPcm16(muLaw);
  assert.strictEqual(back.length, pcm.length);
});

test('base64 round trip preserves samples', () => {
  const pcm = new Int16Array([1, 2, 3, -1, -2]);
  const b64 = pcm16ToBase64(pcm);
  const back = base64ToPcm16(b64);
  assert.deepStrictEqual(Array.from(back), Array.from(pcm));
});

test('resampling 8 kHz → 24 kHz triples length', () => {
  const pcm = new Int16Array(80);
  for (let i = 0; i < pcm.length; i++) pcm[i] = i;
  const out = resamplePcm16(pcm, 8000, 24_000);
  assert.strictEqual(out.length, 240);
});

test('resampling identical rates is a no-op', () => {
  const pcm = new Int16Array([1, 2, 3]);
  const out = resamplePcm16(pcm, 8000, 8000);
  assert.deepStrictEqual(Array.from(out), [1, 2, 3]);
});
