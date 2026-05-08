import WebSocket from 'ws';
import type { Settings } from '../settings.js';
import type { CoreClient, SessionConfig } from '../core-client/index.js';
import { log } from '../logging.js';
import {
  functionCallOutput,
  inputAudioAppend,
  responseCreate,
  type RealtimeServerEvent,
} from './events.js';
import { TranscriptionSession } from './transcription.js';

export interface SessionHandlers {
  onAudioDelta?: (base64Audio: string) => void;
  onTranscriptDelta?: (text: string) => void;
  onUserTranscript?: (text: string) => void;
  onResponseDone?: (responseId: string) => void;
  onClosed?: () => void;
}

/**
 * Test-only seam for swapping the WebSocket constructor and the
 * transcription-sidecar factory. Production code never sets these.
 */
export type SessionWSFactory = (
  url: string,
  options?: WebSocket.ClientOptions,
) => WebSocket;
export interface RealtimeSessionOptions {
  /** When true, run a `gpt-realtime-whisper` sidecar always-on, regardless of mode. */
  auditTranscripts?: boolean;
  wsFactory?: SessionWSFactory;
  transcriptionFactory?: (conversationId: string) => TranscriptionSession;
}

const defaultWsFactory: SessionWSFactory = (url, options) => new WebSocket(url, options);

export class RealtimeSession {
  private ws: WebSocket | null = null;
  private model: string;
  private closed = false;
  private startTs = Date.now();
  /** When set, every inbound audio frame fans out to this whisper-only WS. */
  private sidecar: TranscriptionSession | null = null;
  private readonly auditTranscripts: boolean;
  private readonly wsFactory: SessionWSFactory;
  private readonly transcriptionFactory: (conversationId: string) => TranscriptionSession;

  constructor(
    private readonly settings: Settings,
    private readonly core: CoreClient,
    private readonly config: SessionConfig,
    private readonly handlers: SessionHandlers = {},
    opts: RealtimeSessionOptions = {},
  ) {
    this.model =
      config.mode === 'translate' ? settings.openaiTranslateModel : settings.openaiRealtimeModel;
    this.auditTranscripts = opts.auditTranscripts ?? false;
    this.wsFactory = opts.wsFactory ?? defaultWsFactory;
    this.transcriptionFactory =
      opts.transcriptionFactory ??
      ((conversationId) =>
        new TranscriptionSession(this.settings, this.core, { conversationId }));
  }

  get conversationId(): string {
    return this.config.conversation_id;
  }

  /** True when the session is currently in a configuration that warrants a whisper sidecar. */
  private shouldHaveSidecar(): boolean {
    return this.auditTranscripts || this.model === this.settings.openaiTranslateModel;
  }

  async open(): Promise<void> {
    if (!this.settings.openaiApiKey) {
      log.warn({ conv: this.config.conversation_id }, 'openai_api_key_missing_using_mock');
      return;
    }
    const url = `wss://api.openai.com/v1/realtime?model=${encodeURIComponent(this.model)}`;
    const ws = this.wsFactory(url, {
      headers: { Authorization: `Bearer ${this.settings.openaiApiKey}` },
    });
    this.ws = ws;
    this.closed = false;

    ws.on('open', () => {
      log.info(
        { conv: this.config.conversation_id, model: this.model },
        'openai_realtime_open',
      );
      // GA Realtime API session shape (post-Sept 2026 launch):
      //   - `session.type` is required and must be "realtime"
      //   - audio config is nested under `audio.input` / `audio.output`
      //   - voice lives at `audio.output.voice`
      //   - turn_detection lives at `audio.input.turn_detection`
      //   - `modalities` was renamed to `output_modalities`
      this.send({
        type: 'session.update',
        session: {
          type: 'realtime',
          model: this.model,
          instructions: this.config.prompt,
          output_modalities: ['audio'],
          tools: this.config.tools,
          audio: {
            input: {
              format: { type: 'audio/pcm', rate: 24_000 },
              turn_detection: { type: 'semantic_vad' },
              transcription: { model: 'whisper-1' },
            },
            output: {
              format: { type: 'audio/pcm', rate: 24_000 },
              voice: this.config.voice,
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
        log.error({ err }, 'openai_event_parse_failed');
      }
    });

    ws.on('close', () => {
      log.info({ conv: this.config.conversation_id }, 'openai_realtime_closed');
      this.closed = true;
      this.handlers.onClosed?.();
    });

    ws.on('error', (err) => {
      log.error({ err, conv: this.config.conversation_id }, 'openai_realtime_error');
    });

    // For audit-flagged verticals, open the sidecar in parallel with the
    // primary session so total startup latency is max(open, sidecar) rather
    // than sum. For translate mode, the sidecar is opened lazily on first
    // audio (see appendAudio).
    if (this.auditTranscripts) {
      this.ensureSidecar();
    }
  }

  /**
   * Switches the active OpenAI model. Tears down the primary WS and reopens.
   * Sidecar lifecycle is reconciled afterwards based on `shouldHaveSidecar()`.
   */
  async switchModel(mode: 'realtime2' | 'translate'): Promise<void> {
    const newModel =
      mode === 'translate' ? this.settings.openaiTranslateModel : this.settings.openaiRealtimeModel;
    if (newModel === this.model) return;
    log.info({ conv: this.config.conversation_id, mode }, 'openai_mode_switch');
    this.closePrimary();
    this.model = newModel;
    await this.open();
    // If we left translate mode without auditing, tear down the sidecar.
    if (!this.shouldHaveSidecar()) {
      this.closeSidecar();
    }
  }

  send(event: object): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.ws.send(JSON.stringify(event));
  }

  /**
   * Forwards an audio frame to the OpenAI Realtime WS, and (when applicable)
   * to the whisper sidecar for parallel transcription. The sidecar opens
   * lazily on the first audio frame after entering translate mode — this
   * amortizes its setup latency behind the user's first utterance.
   */
  appendAudio(base64Audio: string): void {
    this.send(inputAudioAppend(base64Audio));
    if (this.shouldHaveSidecar()) {
      this.ensureSidecar();
      this.sidecar?.appendAudio(base64Audio);
    }
  }

  commitInput(): void {
    this.send({ type: 'input_audio_buffer.commit' });
    this.send(responseCreate());
  }

  close(): void {
    this.closePrimary();
    this.closeSidecar();
  }

  private closePrimary(): void {
    if (this.ws && !this.closed) {
      try {
        this.ws.close();
      } catch (err) {
        log.warn({ err, conv: this.config.conversation_id }, 'realtime_close_threw');
      }
    }
    this.ws = null;
    this.closed = true;
  }

  private ensureSidecar(): void {
    if (this.sidecar) return;
    try {
      const sc = this.transcriptionFactory(this.config.conversation_id);
      void sc.open().catch((err) =>
        log.warn({ err, conv: this.config.conversation_id }, 'sidecar_open_failed'),
      );
      this.sidecar = sc;
    } catch (err) {
      // Sidecar failure must NOT take down the primary session.
      log.warn({ err, conv: this.config.conversation_id }, 'sidecar_construct_failed');
      this.sidecar = null;
    }
  }

  private closeSidecar(): void {
    if (this.sidecar) {
      try {
        this.sidecar.close();
      } catch (err) {
        log.warn({ err, conv: this.config.conversation_id }, 'sidecar_close_threw');
      }
      this.sidecar = null;
    }
  }

  /** Test seam: returns whether the sidecar is currently constructed. */
  hasSidecar(): boolean {
    return this.sidecar !== null;
  }

  private async handleEvent(event: RealtimeServerEvent): Promise<void> {
    // GA event names: response.output_audio.delta, response.output_audio_transcript.delta,
    // function calls arrive embedded in response.done.output[].
    switch (event.type) {
      case 'response.output_audio.delta':
      case 'response.audio.delta': {
        const delta = (event as { delta?: string }).delta;
        if (delta) this.handlers.onAudioDelta?.(delta);
        return;
      }
      case 'response.output_audio_transcript.delta':
      case 'response.audio_transcript.delta': {
        const delta = (event as { delta?: string }).delta;
        if (delta) this.handlers.onTranscriptDelta?.(delta);
        return;
      }
      case 'conversation.item.input_audio_transcription.completed': {
        const transcript = (event as { transcript?: string }).transcript ?? '';
        this.handlers.onUserTranscript?.(transcript);
        // Tag the transcript with the active model so audit/bilingual
        // diff jobs can distinguish agent-side recognition from
        // whisper-side recognition (which is persisted by the sidecar).
        await this.core.pushTranscript(
          this.conversationId,
          'user',
          transcript,
          undefined,
          this.model,
        );
        return;
      }
      case 'response.output_audio_transcript.done':
      case 'response.audio_transcript.done': {
        const transcript = (event as { transcript?: string }).transcript ?? '';
        const latency = Date.now() - this.startTs;
        await this.core.pushTranscript(
          this.conversationId,
          'agent',
          transcript,
          latency,
          this.model,
        );
        return;
      }
      case 'response.done': {
        const response = (event as {
          response?: {
            id?: string;
            output?: Array<{
              type?: string;
              call_id?: string;
              name?: string;
              arguments?: string;
            }>;
          };
        }).response;
        const responseId = response?.id;
        if (responseId) this.handlers.onResponseDone?.(responseId);
        for (const item of response?.output ?? []) {
          if (item.type === 'function_call' && item.call_id && item.name) {
            await this.handleFunctionCall(item.call_id, item.name, item.arguments ?? '{}');
          }
        }
        this.startTs = Date.now();
        return;
      }
      case 'error': {
        log.error({ event, conv: this.conversationId }, 'openai_error_event');
        return;
      }
      default:
        return;
    }
  }

  private async handleFunctionCall(callId: string, name: string, argsJson: string): Promise<void> {
    let args: Record<string, unknown> = {};
    try {
      args = argsJson ? (JSON.parse(argsJson) as Record<string, unknown>) : {};
    } catch (err) {
      log.error({ err, argsJson, name }, 'function_call_args_parse_failed');
    }
    log.info({ conv: this.conversationId, tool: name, args }, 'function_call_dispatch');
    try {
      const result = await this.core.toolCall(this.conversationId, name, args);
      this.send(functionCallOutput(callId, result.result ?? { status: result.status }));
      this.send(responseCreate());
    } catch (err) {
      log.error({ err, conv: this.conversationId, tool: name }, 'function_call_failed');
      this.send(functionCallOutput(callId, { error: String(err) }));
      this.send(responseCreate());
    }
  }
}
