/**
 * TranscriptionSession — wraps a `gpt-realtime-whisper` WebSocket.
 *
 * Used in two distinct shapes:
 *
 *   • SOLO   (voicemail, note-taker): the only OpenAI WebSocket open
 *            for the conversation. No `RealtimeSession`. No tools, no
 *            audio output, no agent persona.
 *
 *   • SIDECAR (translate-bilingual, audit transcripts): runs alongside
 *             a `RealtimeSession`. Same inbound audio fans out to both;
 *             transcripts are persisted with `model='whisper'` to
 *             distinguish them from the agent's own transcripts.
 *
 * This class is mode-agnostic; whether it is solo or sidecar is decided
 * by the caller (`signaling.ts`, `media-stream.ts`, `session.ts`).
 */

import WebSocket from 'ws';
import type { Settings } from '../settings.js';
import type { CoreClient } from '../core-client/index.js';
import { log } from '../logging.js';
import { inputAudioAppend, type RealtimeServerEvent } from './events.js';

export interface TranscriptionHandlers {
  onUserTranscript?: (text: string) => void;
  onPartialTranscript?: (text: string) => void;
  onClosed?: () => void;
}

export interface TranscriptionConfig {
  conversationId: string;
  /** Tag applied to each completed transcript when persisted into app.turns. */
  roleLabel?: 'user' | 'agent';
}

/**
 * Test-only seam: in unit tests, the WebSocket factory can be replaced
 * via this hook. Production code never sets it; the default uses
 * `new WebSocket(url, options)` from the `ws` package.
 */
export type WSFactory = (url: string, options?: WebSocket.ClientOptions) => WebSocket;
export interface TranscriptionSessionOptions {
  wsFactory?: WSFactory;
}

const defaultWsFactory: WSFactory = (url, options) => new WebSocket(url, options);

export class TranscriptionSession {
  private ws: WebSocket | null = null;
  private closed = false;
  private opened = false;
  private readonly model: string;

  constructor(
    private readonly settings: Settings,
    private readonly core: CoreClient,
    private readonly config: TranscriptionConfig,
    private readonly handlers: TranscriptionHandlers = {},
    private readonly opts: TranscriptionSessionOptions = {},
  ) {
    this.model = this.settings.openaiWhisperModel;
  }

  get conversationId(): string {
    return this.config.conversationId;
  }

  get isOpen(): boolean {
    return this.opened && !this.closed && this.ws?.readyState === WebSocket.OPEN;
  }

  /** Opens the whisper WebSocket and sends a transcription-only session.update. */
  async open(): Promise<void> {
    if (this.opened) return;
    if (!this.settings.openaiApiKey) {
      log.warn(
        { conv: this.config.conversationId },
        'transcription_session_no_api_key_using_mock',
      );
      this.opened = true;
      return;
    }
    const url = `wss://api.openai.com/v1/realtime?model=${encodeURIComponent(this.model)}`;
    const factory = this.opts.wsFactory ?? defaultWsFactory;
    const ws = factory(url, {
      headers: { Authorization: `Bearer ${this.settings.openaiApiKey}` },
    });
    this.ws = ws;
    this.opened = true;

    ws.on('open', () => {
      log.info(
        { conv: this.config.conversationId, model: this.model },
        'transcription_session_open',
      );
      // Whisper-only session shape: no tools, no audio output,
      // no instructions. We just ask it to transcribe the input
      // audio buffer.
      this.send({
        type: 'session.update',
        session: {
          type: 'transcription',
          audio: {
            input: {
              format: { type: 'audio/pcm', rate: 24_000 },
              turn_detection: { type: 'semantic_vad' },
              transcription: { model: 'whisper-1' },
            },
          },
        },
      });
    });

    ws.on('message', (raw) => {
      try {
        const event = JSON.parse(raw.toString()) as RealtimeServerEvent;
        void this.handleEvent(event);
      } catch (err) {
        log.error({ err }, 'transcription_event_parse_failed');
      }
    });

    ws.on('close', () => {
      log.info({ conv: this.config.conversationId }, 'transcription_session_closed');
      this.closed = true;
      this.handlers.onClosed?.();
    });

    ws.on('error', (err) => {
      log.error(
        { err, conv: this.config.conversationId },
        'transcription_session_error',
      );
    });
  }

  /** Append a base64 PCM-24kHz audio frame. */
  appendAudio(base64Audio: string): void {
    if (!this.isOpen) return;
    this.send(inputAudioAppend(base64Audio));
  }

  close(): void {
    if (this.ws && !this.closed) {
      try {
        this.ws.close();
      } catch (err) {
        log.warn({ err, conv: this.config.conversationId }, 'transcription_close_threw');
      }
    }
    this.ws = null;
    this.closed = true;
  }

  private send(event: object): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.ws.send(JSON.stringify(event));
  }

  private async handleEvent(event: RealtimeServerEvent): Promise<void> {
    switch (event.type) {
      case 'conversation.item.input_audio_transcription.completed': {
        const transcript = (event as { transcript?: string }).transcript ?? '';
        if (!transcript) return;
        this.handlers.onUserTranscript?.(transcript);
        try {
          await this.core.pushTranscript(
            this.config.conversationId,
            this.config.roleLabel ?? 'user',
            transcript,
            undefined,
            'whisper',
          );
        } catch (err) {
          log.error({ err, conv: this.config.conversationId }, 'transcription_persist_failed');
        }
        return;
      }
      case 'conversation.item.input_audio_transcription.delta': {
        const delta = (event as { delta?: string }).delta;
        if (delta) this.handlers.onPartialTranscript?.(delta);
        return;
      }
      case 'error': {
        log.error(
          { event, conv: this.config.conversationId },
          'transcription_server_error_event',
        );
        return;
      }
      default:
        return;
    }
  }
}
