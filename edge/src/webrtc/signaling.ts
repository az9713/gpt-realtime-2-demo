import type { FastifyInstance } from 'fastify';
import type WebSocket from 'ws';
import type { Settings } from '../settings.js';
import { getCoreClient } from '../core-client/index.js';
import { RealtimeSession } from '../openai/session.js';
import { TranscriptionSession } from '../openai/transcription.js';
import { dropSession, registerSession } from '../openai/sessions-registry.js';
import { feedAudio, startVoiceIntent, stopVoiceIntent } from '../voice-intent/classifier.js';
import { log } from '../logging.js';

type BrowserMode = 'realtime2' | 'translate' | 'notetaker';

interface BrowserClientEvent {
  kind: 'audio.append' | 'audio.commit' | 'mode.switch' | 'end' | 'hello';
  audio?: string;
  /** Mid-session swaps — only between realtime2 and translate. */
  mode?: 'realtime2' | 'translate';
  vertical?: string;
  language?: string;
}

interface BrowserServerEvent {
  kind: string;
  [k: string]: unknown;
}

const NOTETAKER_MODE: BrowserMode = 'notetaker';

/**
 * Browser transport. Two flavors:
 *
 *   * Agent mode (default `realtime2`, optional `translate`) — opens a
 *     `RealtimeSession` against gpt-realtime-2 / gpt-realtime-translate
 *     and runs the full voice agent loop with tools and approvals.
 *
 *   * Note-taker mode (`mode=notetaker`) — opens a `TranscriptionSession`
 *     directly. No agent persona, no tools, no audio playback, no voice-
 *     intent classifier. The dispatcher converses with the caller (or
 *     speaks aloud) and whisper silently transcribes into app.turns.
 */
export function registerWebRtcSignaling(app: FastifyInstance, settings: Settings): void {
  const core = getCoreClient(settings);

  app.get('/v1/voice/browser', { websocket: true }, (socket: WebSocket, request) => {
    const url = new URL(request.url, `http://${request.headers.host}`);
    const surface = 'browser' as const;
    const vertical = url.searchParams.get('vertical') ?? undefined;
    const mode = (url.searchParams.get('mode') ?? 'realtime2') as BrowserMode;
    const language = url.searchParams.get('language') ?? undefined;

    const send = (msg: BrowserServerEvent): void => {
      socket.send(JSON.stringify(msg));
    };

    let session: RealtimeSession | null = null;
    let notetaker: TranscriptionSession | null = null;
    let conversationId: string | null = null;

    const startAgentSession = async (): Promise<void> => {
      const config = await core.createSession({
        surface,
        ...(vertical !== undefined ? { vertical } : {}),
        mode: mode as 'realtime2' | 'translate',
        ...(language !== undefined ? { language } : {}),
      });
      conversationId = config.conversation_id;
      session = new RealtimeSession(settings, core, config, {
        onAudioDelta: (b64) => send({ kind: 'audio.delta', audio: b64 }),
        onTranscriptDelta: (delta) => send({ kind: 'transcript.delta', text: delta }),
        onUserTranscript: (text) => send({ kind: 'transcript.user', text }),
        onResponseDone: (id) => send({ kind: 'response.done', response_id: id }),
        onClosed: () => send({ kind: 'session.closed' }),
      });
      registerSession(session);
      await session.open();
      send({
        kind: 'session.created',
        conversation_id: config.conversation_id,
        vertical: config.vertical,
        mode: config.mode,
      });
      startVoiceIntent(config.conversation_id, settings, core);
    };

    const startNotetakerSession = async (): Promise<void> => {
      const config = await core.createSession({
        surface,
        ...(vertical !== undefined ? { vertical } : {}),
        mode: 'notetaker',
        ...(language !== undefined ? { language } : {}),
      });
      conversationId = config.conversation_id;
      notetaker = new TranscriptionSession(
        settings,
        core,
        { conversationId: config.conversation_id },
        {
          onUserTranscript: (text) => send({ kind: 'transcript.user', text }),
          onPartialTranscript: (delta) => send({ kind: 'transcript.delta', text: delta }),
          onClosed: () => send({ kind: 'session.closed' }),
        },
      );
      await notetaker.open();
      send({
        kind: 'session.created',
        conversation_id: config.conversation_id,
        vertical: config.vertical,
        mode: NOTETAKER_MODE,
      });
    };

    const startSession = mode === NOTETAKER_MODE ? startNotetakerSession : startAgentSession;

    void startSession().catch((err) => {
      log.error({ err, mode }, 'browser_session_start_failed');
      send({ kind: 'error', error: String(err) });
      socket.close();
    });

    socket.on('message', (raw: WebSocket.RawData) => {
      let msg: BrowserClientEvent;
      try {
        msg = JSON.parse(raw.toString()) as BrowserClientEvent;
      } catch {
        return;
      }
      switch (msg.kind) {
        case 'audio.append':
          if (msg.audio) {
            if (session) {
              session.appendAudio(msg.audio);
              feedAudio(session.conversationId, msg.audio);
            } else if (notetaker) {
              notetaker.appendAudio(msg.audio);
            }
          }
          return;
        case 'audio.commit':
          // No-op in notetaker mode (whisper handles VAD itself).
          if (session) session.commitInput();
          return;
        case 'mode.switch':
          // Only valid in agent mode; voicemail/notetaker are start-time-only.
          if (msg.mode && conversationId && session) {
            const target = msg.mode;
            void core.switchMode(conversationId, target).then(() => session?.switchModel(target));
          }
          return;
        case 'end':
          socket.close();
          return;
        case 'hello':
          return;
        default:
          return;
      }
    });

    socket.on('close', () => {
      if (session) {
        session.close();
        dropSession(session.conversationId);
        stopVoiceIntent(session.conversationId);
      }
      if (notetaker) {
        notetaker.close();
      }
      if (conversationId) {
        void core.endSession(conversationId).catch(() => undefined);
      }
    });
  });
}
