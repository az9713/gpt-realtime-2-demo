import type { FastifyInstance } from 'fastify';
import type WebSocket from 'ws';
import type { Settings } from '../settings.js';
import type { CoreClient } from '../core-client/index.js';
import { RealtimeSession } from '../openai/session.js';
import { TranscriptionSession } from '../openai/transcription.js';
import { dropSession, registerSession } from '../openai/sessions-registry.js';
import {
  base64ToPcm16,
  muLawToPcm16,
  pcm16ToBase64,
  pcm16ToMuLaw,
  resamplePcm16,
} from './audio.js';
import { feedAudio, startVoiceIntent, stopVoiceIntent } from '../voice-intent/classifier.js';
import { log } from '../logging.js';

interface TwilioMediaEvent {
  event: 'connected' | 'start' | 'media' | 'stop' | 'mark';
  start?: { streamSid: string; callSid: string; customParameters?: Record<string, string> };
  media?: { payload: string };
  stop?: { reason?: string };
}

export function registerTwilioMediaStream(app: FastifyInstance, settings: Settings): void {
  app.get('/twilio/media-stream', { websocket: true }, (socket: WebSocket, _request) => {
    let session: RealtimeSession | null = null;
    let voicemail: TranscriptionSession | null = null;
    let conversationId: string | null = null;
    let streamSid: string | null = null;
    const core = (app as unknown as { _core?: CoreClient })._core;

    const send = (msg: object): void => socket.send(JSON.stringify(msg));

    const onAgentAudioDelta = (b64Pcm24: string): void => {
      if (!streamSid) return;
      const pcm24 = base64ToPcm16(b64Pcm24);
      const pcm8 = resamplePcm16(pcm24, 24_000, 8_000);
      const muLaw = pcm16ToMuLaw(pcm8);
      send({
        event: 'media',
        streamSid,
        media: { payload: muLaw.toString('base64') },
      });
    };

    const startAgentSession = async (vertical: string | undefined): Promise<void> => {
      if (!core) throw new Error('core client not registered');
      const config = await core.createSession({
        surface: 'phone',
        ...(vertical !== undefined ? { vertical } : {}),
      });
      conversationId = config.conversation_id;
      session = new RealtimeSession(settings, core, config, {
        onAudioDelta: onAgentAudioDelta,
      });
      registerSession(session);
      await session.open();
      startVoiceIntent(config.conversation_id, settings, core);
    };

    const startVoicemailSession = async (vertical: string | undefined): Promise<void> => {
      if (!core) throw new Error('core client not registered');
      const config = await core.createSession({
        surface: 'phone',
        mode: 'voicemail',
        ...(vertical !== undefined ? { vertical } : {}),
      });
      conversationId = config.conversation_id;
      voicemail = new TranscriptionSession(settings, core, {
        conversationId: config.conversation_id,
      });
      await voicemail.open();
      log.info(
        { conv: config.conversation_id, vertical },
        'voicemail_session_started',
      );
    };

    socket.on('message', (raw: WebSocket.RawData) => {
      let event: TwilioMediaEvent;
      try {
        event = JSON.parse(raw.toString()) as TwilioMediaEvent;
      } catch {
        return;
      }
      switch (event.event) {
        case 'start': {
          streamSid = event.start?.streamSid ?? null;
          const vertical = event.start?.customParameters?.vertical;
          const mode = event.start?.customParameters?.mode;
          if (mode === 'voicemail') {
            void startVoicemailSession(vertical).catch((err) =>
              log.error({ err }, 'twilio_voicemail_start_failed'),
            );
          } else {
            void startAgentSession(vertical).catch((err) =>
              log.error({ err }, 'twilio_start_failed'),
            );
          }
          return;
        }
        case 'media': {
          if (!event.media) return;
          const muLawBuf = Buffer.from(event.media.payload, 'base64');
          const pcm8 = muLawToPcm16(muLawBuf);
          const pcm24 = resamplePcm16(pcm8, 8_000, 24_000);
          const b64 = pcm16ToBase64(pcm24);
          if (session) {
            session.appendAudio(b64);
            feedAudio(session.conversationId, b64);
          } else if (voicemail) {
            voicemail.appendAudio(b64);
          }
          return;
        }
        case 'stop': {
          if (session) {
            session.close();
            dropSession(session.conversationId);
            stopVoiceIntent(session.conversationId);
          }
          if (voicemail) {
            voicemail.close();
          }
          if (conversationId && core) {
            void core.endSession(conversationId).catch(() => undefined);
          }
          return;
        }
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
      if (voicemail) {
        voicemail.close();
      }
      if (conversationId && core) {
        void core.endSession(conversationId).catch(() => undefined);
      }
    });
  });
}
