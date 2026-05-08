import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { RealtimeSession } from '../src/openai/session.js';
import { TranscriptionSession } from '../src/openai/transcription.js';
import { MockOpenAIWebSocket } from './_fixtures/mock-openai-ws.js';
import type { Settings } from '../src/settings.js';
import type { SessionConfig } from '../src/core-client/index.js';

function fakeSettings(): Settings {
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
  };
}

function fakeConfig(mode: 'realtime2' | 'translate'): SessionConfig {
  return {
    conversation_id: 'c-1',
    vertical: 'hvac',
    surface: 'browser',
    mode,
    persona: 'Aria',
    prompt: 'be a helpful HVAC dispatcher',
    tools: [],
    voice: 'alloy',
    realtime_model: 'gpt-realtime-2',
    translate_model: 'gpt-realtime-translate',
    auto_translate_non_english: true,
  };
}

class FakeCoreClient {
  pushed: Array<{ role: string; text: string; model?: string }> = [];
  async pushTranscript(
    _conv: string,
    role: 'user' | 'agent' | 'system' | 'tool',
    text: string,
    _latencyMs?: number,
    model?: string,
  ): Promise<void> {
    this.pushed.push({ role, text, model });
  }
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

class StubTranscriptionSession {
  opened = false;
  appended: string[] = [];
  closed = false;
  constructor(public readonly conversationId: string) {}
  async open(): Promise<void> {
    this.opened = true;
  }
  appendAudio(b64: string): void {
    this.appended.push(b64);
  }
  close(): void {
    this.closed = true;
  }
  get isOpen(): boolean {
    return this.opened && !this.closed;
  }
}

test('realtime2 mode does NOT open a sidecar', async () => {
  const sockets: MockOpenAIWebSocket[] = [];
  const stubs: StubTranscriptionSession[] = [];
  const sess = new RealtimeSession(
    fakeSettings(),
    new FakeCoreClient() as never,
    fakeConfig('realtime2'),
    {},
    {
      wsFactory: (url, opts) => {
        const m = new MockOpenAIWebSocket(url, opts as Record<string, unknown>);
        sockets.push(m);
        return m as unknown as import('ws').WebSocket;
      },
      transcriptionFactory: (cid) => {
        const s = new StubTranscriptionSession(cid);
        stubs.push(s);
        return s as unknown as TranscriptionSession;
      },
    },
  );
  await sess.open();
  await new Promise((r) => setImmediate(r));
  sess.appendAudio('AAAA');
  assert.equal(stubs.length, 0, 'no sidecar should be constructed in realtime2 mode');
  assert.equal(sess.hasSidecar(), false);
});

test('translate mode opens sidecar lazily on first audio frame', async () => {
  const stubs: StubTranscriptionSession[] = [];
  const sess = new RealtimeSession(
    fakeSettings(),
    new FakeCoreClient() as never,
    fakeConfig('translate'),
    {},
    {
      wsFactory: (url, opts) =>
        new MockOpenAIWebSocket(url, opts as Record<string, unknown>) as unknown as import('ws').WebSocket,
      transcriptionFactory: (cid) => {
        const s = new StubTranscriptionSession(cid);
        stubs.push(s);
        return s as unknown as TranscriptionSession;
      },
    },
  );
  await sess.open();
  await new Promise((r) => setImmediate(r));
  // Before any audio: no sidecar yet (lazy)
  assert.equal(stubs.length, 0);
  sess.appendAudio('AAAA');
  // First audio kicks off sidecar
  assert.equal(stubs.length, 1);
  assert.deepStrictEqual(stubs[0]!.appended, ['AAAA']);
  // Subsequent audio fans out
  sess.appendAudio('BBBB');
  assert.deepStrictEqual(stubs[0]!.appended, ['AAAA', 'BBBB']);
  assert.equal(sess.hasSidecar(), true);
});

test('switchModel translate->realtime2 closes the sidecar', async () => {
  const stubs: StubTranscriptionSession[] = [];
  const sess = new RealtimeSession(
    fakeSettings(),
    new FakeCoreClient() as never,
    fakeConfig('translate'),
    {},
    {
      wsFactory: (url, opts) =>
        new MockOpenAIWebSocket(url, opts as Record<string, unknown>) as unknown as import('ws').WebSocket,
      transcriptionFactory: (cid) => {
        const s = new StubTranscriptionSession(cid);
        stubs.push(s);
        return s as unknown as TranscriptionSession;
      },
    },
  );
  await sess.open();
  await new Promise((r) => setImmediate(r));
  sess.appendAudio('A');
  assert.equal(stubs.length, 1);
  await sess.switchModel('realtime2');
  await new Promise((r) => setImmediate(r));
  assert.equal(stubs[0]!.closed, true);
  assert.equal(sess.hasSidecar(), false);
});

test('auditTranscripts=true opens sidecar at session start regardless of mode', async () => {
  const stubs: StubTranscriptionSession[] = [];
  const sess = new RealtimeSession(
    fakeSettings(),
    new FakeCoreClient() as never,
    fakeConfig('realtime2'),
    {},
    {
      auditTranscripts: true,
      wsFactory: (url, opts) =>
        new MockOpenAIWebSocket(url, opts as Record<string, unknown>) as unknown as import('ws').WebSocket,
      transcriptionFactory: (cid) => {
        const s = new StubTranscriptionSession(cid);
        stubs.push(s);
        return s as unknown as TranscriptionSession;
      },
    },
  );
  await sess.open();
  await new Promise((r) => setImmediate(r));
  // Audit verticals open sidecar in parallel with the primary, before any audio
  assert.equal(stubs.length, 1);
  assert.equal(sess.hasSidecar(), true);
});

test('user transcript event tags the persisted turn with the active model', async () => {
  const core = new FakeCoreClient();
  let mock: MockOpenAIWebSocket | null = null;
  const sess = new RealtimeSession(
    fakeSettings(),
    core as never,
    fakeConfig('translate'),
    {},
    {
      wsFactory: (url, opts) => {
        const m = new MockOpenAIWebSocket(url, opts as Record<string, unknown>);
        mock = m;
        return m as unknown as import('ws').WebSocket;
      },
      transcriptionFactory: (cid) =>
        new StubTranscriptionSession(cid) as unknown as TranscriptionSession,
    },
  );
  await sess.open();
  await new Promise((r) => setImmediate(r));
  mock!.emitServer({
    type: 'conversation.item.input_audio_transcription.completed',
    transcript: 'hola',
  });
  await new Promise((r) => setImmediate(r));
  assert.equal(core.pushed.length, 1);
  assert.equal(core.pushed[0]!.role, 'user');
  assert.equal(core.pushed[0]!.model, 'gpt-realtime-translate');
});

test('close() tears down both primary and sidecar', async () => {
  const stubs: StubTranscriptionSession[] = [];
  const sess = new RealtimeSession(
    fakeSettings(),
    new FakeCoreClient() as never,
    fakeConfig('translate'),
    {},
    {
      wsFactory: (url, opts) =>
        new MockOpenAIWebSocket(url, opts as Record<string, unknown>) as unknown as import('ws').WebSocket,
      transcriptionFactory: (cid) => {
        const s = new StubTranscriptionSession(cid);
        stubs.push(s);
        return s as unknown as TranscriptionSession;
      },
    },
  );
  await sess.open();
  await new Promise((r) => setImmediate(r));
  sess.appendAudio('A');
  assert.equal(stubs.length, 1);
  sess.close();
  assert.equal(stubs[0]!.closed, true);
  assert.equal(sess.hasSidecar(), false);
});
