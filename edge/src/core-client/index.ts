import type { FastifyInstance } from 'fastify';
import type { Settings } from '../settings.js';
import { request } from 'undici';
import WebSocket from 'ws';
import { log } from '../logging.js';

export interface SessionConfig {
  conversation_id: string;
  vertical: string;
  surface: 'browser' | 'phone';
  mode: 'realtime2' | 'translate';
  persona: string;
  prompt: string;
  tools: unknown[];
  voice: string;
  realtime_model: string;
  translate_model: string;
  auto_translate_non_english: boolean;
}

export interface ToolCallResponse {
  tool_call_id: string;
  status: 'executed' | 'pending_approval' | 'failed' | 'denied';
  result: unknown;
  error: string | null;
}

export class CoreClient {
  constructor(private readonly settings: Settings) {}

  async createSession(body: {
    surface: 'browser' | 'phone';
    vertical?: string;
    mode?: 'realtime2' | 'translate';
    language?: string;
  }): Promise<SessionConfig> {
    const res = await request(`${this.settings.coreHttpUrl}/v1/sessions`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (res.statusCode >= 400) {
      const text = await res.body.text();
      throw new Error(`createSession failed: ${res.statusCode} ${text}`);
    }
    return (await res.body.json()) as SessionConfig;
  }

  async toolCall(
    conversationId: string,
    toolName: string,
    args: Record<string, unknown>,
    turnId?: string,
  ): Promise<ToolCallResponse> {
    const res = await request(
      `${this.settings.coreHttpUrl}/v1/sessions/${conversationId}/tool-calls`,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ tool_name: toolName, args, turn_id: turnId }),
      },
    );
    if (res.statusCode >= 400) {
      const text = await res.body.text();
      throw new Error(`toolCall failed: ${res.statusCode} ${text}`);
    }
    return (await res.body.json()) as ToolCallResponse;
  }

  async endSession(conversationId: string): Promise<void> {
    const res = await request(`${this.settings.coreHttpUrl}/v1/sessions/${conversationId}/end`, {
      method: 'POST',
    });
    await res.body.dump();
  }

  async switchMode(
    conversationId: string,
    mode: 'realtime2' | 'translate',
  ): Promise<void> {
    const res = await request(
      `${this.settings.coreHttpUrl}/v1/sessions/${conversationId}/mode`,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ mode }),
      },
    );
    await res.body.dump();
  }

  async pushTranscript(
    conversationId: string,
    role: 'user' | 'agent' | 'system' | 'tool',
    text: string,
    latencyMs?: number,
    model?: string,
  ): Promise<void> {
    const body: Record<string, unknown> = { role, text };
    if (latencyMs !== undefined) body.latency_ms = latencyMs;
    if (model !== undefined) body.model = model;
    const res = await request(
      `${this.settings.coreHttpUrl}/v1/sessions/${conversationId}/transcript`,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      },
    );
    await res.body.dump();
  }

  async approvalByVoice(conversationId: string, phrase: string): Promise<void> {
    const res = await request(
      `${this.settings.coreHttpUrl}/v1/sessions/${conversationId}/approval-by-voice`,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ phrase }),
      },
    );
    await res.body.dump();
  }

  openEvents(conversationId: string): WebSocket {
    const url = `${this.settings.coreWsUrl}/v1/sessions/${conversationId}/events`;
    const ws = new WebSocket(url);
    ws.on('error', (err) => log.error({ err, conversationId }, 'core_events_ws_error'));
    return ws;
  }
}

let _client: CoreClient | undefined;

export function getCoreClient(settings: Settings): CoreClient {
  if (!_client) _client = new CoreClient(settings);
  return _client;
}

export function registerCoreClient(_app: FastifyInstance, settings: Settings): void {
  getCoreClient(settings);
}
