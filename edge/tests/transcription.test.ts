import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { TranscriptionSession } from '../src/openai/transcription.js';
import { MockOpenAIWebSocket } from './_fixtures/mock-openai-ws.js';
import type { Settings } from '../src/settings.js';

function fakeSettings(overrides: Partial<Settings> = {}): Settings {
  return {
    port: 8080,
    coreHttpUrl: 'http://core:8000',
    coreWsUrl: 'ws://core:8000',
    openaiApiKey: 'sk-test-fake-key-not-used',
    openaiRealtimeModel: 'gpt-realtime-2',
    openaiTranslateModel: 'gpt-realtime-translate',
    openaiWhisperModel: 'gpt-realtime-whisper',
    openaiVoice: 'alloy',
    twilioAccountSid: '',
    twilioAuthToken: '',
    publicBaseUrl: 'http://localhost:8080',
    phoneVerticalMap: {},
    logLevel: 'silent',
    ...overrides,
  };
}

class FakeCoreClient {
  pushed: Array<{
    conv: string;
    role: string;
    text: string;
    latency?: number;
    model?: string;
  }> = [];

  async pushTranscript(
    conversationId: string,
    role: 'user' | 'agent' | 'system' | 'tool',
    text: string,
    latencyMs?: number,
    model?: string,
  ): Promise<void> {
    this.pushed.push({ conv: conversationId, role, text, latency: latencyMs, model });
  }
  // remaining CoreClient methods unused in these tests
  async createSession(): Promise<never> {
    throw new Error('not used');
  }
  async toolCall(): Promise<never> {
    throw new Error('not used');
  }
  async endSession(): Promise<void> {
    /* noop */
  }
  async switchMode(): Promise<void> {
    /* noop */
  }
  async approvalByVoice(): Promise<void> {
    /* noop */
  }
  openEvents(): never {
    throw new Error('not used');
  }
}

test('open() sends a transcription-shaped session.update', async () => {
  const sockets: MockOpenAIWebSocket[] = [];
  const ts = new TranscriptionSession(
    fakeSettings(),
    new FakeCoreClient() as never,
    { conversationId: 'conv-1' },
    {},
    {
      wsFactory: ((url: string, opts: object) => {
        const m = new MockOpenAIWebSocket(url, opts as Record<string, unknown>);
        sockets.push(m);
        return m;
      }) as never,
    },
  );

  await ts.open();
  // microtask delay so the constructed WS fires 'open' and our session.update is sent
  await new Promise((r) => setImmediate(r));

  // URL must hit the dedicated transcription endpoint; passing `?model=...`
  // is rejected with "You must not provide a model parameter for transcription
  // sessions."
  assert.equal(sockets.length, 1);
  assert.ok(
    sockets[0]!.url.includes('intent=transcription'),
    'transcription WS URL must include intent=transcription',
  );
  assert.ok(
    !sockets[0]!.url.includes('model='),
    'transcription WS URL must NOT include model= query',
  );

  const sent = sockets[0]!.firstSentOfType('session.update');
  assert.ok(sent, 'session.update should have been sent');

  const session = (sent as { session: Record<string, unknown> }).session;
  assert.equal(session.type, 'transcription');
  assert.ok(!('output_modalities' in session), 'should not declare output_modalities');
  assert.ok(!('tools' in session), 'should not declare tools');
  assert.ok(!('instructions' in session), 'should not declare instructions');

  const audio = session.audio as {
    input?: Record<string, unknown>;
    output?: Record<string, unknown>;
  };
  assert.ok(audio.input, 'audio.input present');
  assert.ok(!audio.output, 'audio.output should not be set');
  // GA whisper rejects turn_detection: "Turn detection is not supported
  // for this transcription model."
  assert.ok(
    !('turn_detection' in (audio.input ?? {})),
    'audio.input must NOT carry turn_detection',
  );
  // Model id flows through audio.input.transcription.model, not the URL.
  const transcription = (audio.input as Record<string, unknown>).transcription as {
    model?: string;
  };
  assert.equal(transcription.model, 'gpt-realtime-whisper');
});

test('completed transcript event is forwarded and persisted with model=whisper', async () => {
  const core = new FakeCoreClient();
  const seen: string[] = [];
  const sockets: MockOpenAIWebSocket[] = [];
  const ts = new TranscriptionSession(
    fakeSettings(),
    core as never,
    { conversationId: 'conv-9' },
    { onUserTranscript: (t) => seen.push(t) },
    {
      wsFactory: ((url: string, opts: object) => {
        const m = new MockOpenAIWebSocket(url, opts as Record<string, unknown>);
        sockets.push(m);
        return m;
      }) as never,
    },
  );

  await ts.open();
  await new Promise((r) => setImmediate(r));
  const ws = sockets[0]!;
  ws.emitServer({
    type: 'conversation.item.input_audio_transcription.completed',
    transcript: 'Hola, necesito agendar.',
  });
  // give the async persist a tick
  await new Promise((r) => setImmediate(r));

  assert.deepStrictEqual(seen, ['Hola, necesito agendar.']);
  assert.equal(core.pushed.length, 1);
  assert.equal(core.pushed[0]!.conv, 'conv-9');
  assert.equal(core.pushed[0]!.role, 'user');
  assert.equal(core.pushed[0]!.text, 'Hola, necesito agendar.');
  assert.equal(core.pushed[0]!.model, 'whisper');
});

test('appendAudio sends input_audio_buffer.append events', async () => {
  const sockets: MockOpenAIWebSocket[] = [];
  const ts = new TranscriptionSession(
    fakeSettings(),
    new FakeCoreClient() as never,
    { conversationId: 'conv-2' },
    {},
    {
      wsFactory: ((url: string, opts: object) => {
        const m = new MockOpenAIWebSocket(url, opts as Record<string, unknown>);
        sockets.push(m);
        return m;
      }) as never,
    },
  );
  await ts.open();
  await new Promise((r) => setImmediate(r));

  ts.appendAudio('AAAA');
  ts.appendAudio('BBBB');

  const audioFrames = sockets[0]!
    .sentParsed()
    .filter((m) => (m as { type?: string }).type === 'input_audio_buffer.append');
  assert.equal(audioFrames.length, 2);
  assert.equal((audioFrames[0] as { audio: string }).audio, 'AAAA');
  assert.equal((audioFrames[1] as { audio: string }).audio, 'BBBB');
});

test('isOpen flips false after close()', async () => {
  const sockets: MockOpenAIWebSocket[] = [];
  const ts = new TranscriptionSession(
    fakeSettings(),
    new FakeCoreClient() as never,
    { conversationId: 'conv-3' },
    {},
    {
      wsFactory: ((url: string, opts: object) => {
        const m = new MockOpenAIWebSocket(url, opts as Record<string, unknown>);
        sockets.push(m);
        return m;
      }) as never,
    },
  );
  await ts.open();
  await new Promise((r) => setImmediate(r));
  assert.equal(ts.isOpen, true);
  ts.close();
  assert.equal(ts.isOpen, false);
});

test('roleLabel="agent" persists transcript with role agent', async () => {
  const core = new FakeCoreClient();
  const sockets: MockOpenAIWebSocket[] = [];
  const ts = new TranscriptionSession(
    fakeSettings(),
    core as never,
    { conversationId: 'conv-r', roleLabel: 'agent' },
    {},
    {
      wsFactory: ((url: string, opts: object) => {
        const m = new MockOpenAIWebSocket(url, opts as Record<string, unknown>);
        sockets.push(m);
        return m;
      }) as never,
    },
  );
  await ts.open();
  await new Promise((r) => setImmediate(r));
  sockets[0]!.emitServer({
    type: 'conversation.item.input_audio_transcription.completed',
    transcript: 'agent side',
  });
  await new Promise((r) => setImmediate(r));
  assert.equal(core.pushed[0]!.role, 'agent');
});

test('open() with no api key uses mock mode and never opens a socket', async () => {
  const sockets: MockOpenAIWebSocket[] = [];
  const ts = new TranscriptionSession(
    fakeSettings({ openaiApiKey: '' }),
    new FakeCoreClient() as never,
    { conversationId: 'conv-mock' },
    {},
    {
      wsFactory: ((url: string, opts: object) => {
        const m = new MockOpenAIWebSocket(url, opts as Record<string, unknown>);
        sockets.push(m);
        return m;
      }) as never,
    },
  );
  await ts.open();
  assert.equal(sockets.length, 0, 'no WS should be opened without an api key');
  // calling appendAudio is a noop, must not throw
  ts.appendAudio('AAAA');
});
