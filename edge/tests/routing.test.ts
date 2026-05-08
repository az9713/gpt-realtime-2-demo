import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { buildRejectTwiml, buildTwiml, verticalForNumber } from '../src/twilio/routing.js';
import type { Settings } from '../src/settings.js';

const settings: Settings = {
  port: 8080,
  coreHttpUrl: 'http://core:8000',
  coreWsUrl: 'ws://core:8000',
  openaiApiKey: '',
  openaiRealtimeModel: 'gpt-realtime-2',
  openaiTranslateModel: 'gpt-realtime-translate',
  openaiVoice: 'alloy',
  twilioAccountSid: '',
  twilioAuthToken: '',
  publicBaseUrl: 'https://example.test',
  phoneVerticalMap: { '+15555550100': 'hvac' },
  logLevel: 'info',
};

test('verticalForNumber maps configured numbers', () => {
  assert.strictEqual(verticalForNumber(settings, '+15555550100'), 'hvac');
  assert.strictEqual(verticalForNumber(settings, '+15555550101'), undefined);
});

test('buildTwiml streams to correct ws url', () => {
  const xml = buildTwiml(settings, 'hvac');
  assert.match(xml, /wss:\/\/example\.test\/twilio\/media-stream/);
  assert.match(xml, /<Parameter name="vertical" value="hvac"/);
});

test('buildRejectTwiml escapes message', () => {
  const xml = buildRejectTwiml('No <bad> & "scary"');
  assert.match(xml, /&lt;bad&gt;/);
  assert.match(xml, /&amp;/);
  assert.match(xml, /&quot;/);
});
