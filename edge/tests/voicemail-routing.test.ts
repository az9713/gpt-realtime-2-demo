import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { buildVoicemailTwiml } from '../src/twilio/routing.js';
import type { Settings } from '../src/settings.js';

const settings: Settings = {
  port: 8080,
  coreHttpUrl: 'http://core:8000',
  coreWsUrl: 'ws://core:8000',
  openaiApiKey: '',
  openaiRealtimeModel: 'gpt-realtime-2',
  openaiTranslateModel: 'gpt-realtime-translate',
  openaiWhisperModel: 'gpt-realtime-whisper',
  openaiVoice: 'alloy',
  twilioAccountSid: '',
  twilioAuthToken: '',
  publicBaseUrl: 'https://example.test',
  phoneVerticalMap: {},
  logLevel: 'silent',
};

test('buildVoicemailTwiml emits Say + Connect with mode=voicemail', () => {
  const xml = buildVoicemailTwiml(settings, 'hvac', 'You have reached the after-hours line.');
  assert.match(xml, /<Say voice="alice">You have reached the after-hours line\.<\/Say>/);
  assert.match(xml, /wss:\/\/example\.test\/twilio\/media-stream/);
  assert.match(xml, /<Parameter name="vertical" value="hvac"/);
  assert.match(xml, /<Parameter name="mode" value="voicemail"/);
});

test('buildVoicemailTwiml escapes greeting xml characters', () => {
  const xml = buildVoicemailTwiml(settings, 'hvac', 'A & B "scary" <message>');
  assert.match(xml, /A &amp; B &quot;scary&quot; &lt;message&gt;/);
});

test('buildVoicemailTwiml without vertical omits the vertical parameter', () => {
  const xml = buildVoicemailTwiml(settings, undefined, 'Hi.');
  assert.doesNotMatch(xml, /<Parameter name="vertical"/);
  assert.match(xml, /<Parameter name="mode" value="voicemail"/);
});
