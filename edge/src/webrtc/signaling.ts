import type { FastifyInstance } from 'fastify';
import type WebSocket from 'ws';
import type { Settings } from '../settings.js';
import { getCoreClient } from '../core-client/index.js';
import { RealtimeSession } from '../openai/session.js';
import { dropSession, registerSession } from '../openai/sessions-registry.js';
import { feedAudio, startVoiceIntent, stopVoiceIntent } from '../voice-intent/classifier.js';
import { log } from '../logging.js';

interface BrowserClientEvent {
  kind: 'audio.append' | 'audio.commit' | 'mode.switch' | 'end' | 'hello';
  audio?: string;
  mode?: 'realtime2' | 'translate';
  vertical?: string;
  language?: string;
}

interface BrowserServerEvent {
  kind: string;
  [k: string]: unknown;
}

/**
 * v1 browser transport: a single WebSocket carrying both signaling and
 * base64-encoded PCM frames. Pure WebRTC offer/answer is reserved for a
 * later iteration; this keeps the dev story trivially testable.
 */
export function registerWebRtcSignaling(app: FastifyInstance, settings: Settings): void {
  const core = getCoreClient(settings);

  app.get('/v1/voice/browser', { websocket: true }, (socket: WebSocket, request) => {
    const url = new URL(request.url, `http://${request.headers.host}`);
    const surface = 'browser' as const;
    const vertical = url.searchParams.get('vertical') ?? undefined;
    const mode = (url.searchParams.get('mode') ?? 'realtime2') as 'realtime2' | 'translate';
    const language = url.searchParams.get('language') ?? undefined;

    const send = (msg: BrowserServerEvent): void => {
      socket.send(JSON.stringify(msg));
    };

    let session: RealtimeSession | null = null;
    let conversationId: string | null = null;

    const startSession = async (): Promise<void> => {
      const config = await core.createSession({
        surface,
        ...(vertical !== undefined ? { vertical } : {}),
        mode,
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

    void startSession().catch((err) => {
      log.error({ err }, 'browser_session_start_failed');
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
      if (!session) return;
      switch (msg.kind) {
        case 'audio.append':
          if (msg.audio) {
            session.appendAudio(msg.audio);
            feedAudio(session.conversationId, msg.audio);
          }
          return;
        case 'audio.commit':
          session.commitInput();
          return;
        case 'mode.switch':
          if (msg.mode && conversationId) {
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
      if (conversationId) {
        void core.endSession(conversationId).catch(() => undefined);
      }
    });
  });
}
