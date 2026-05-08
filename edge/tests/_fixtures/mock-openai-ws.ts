/**
 * MockOpenAIWebSocket — a minimal, in-memory replacement for the
 * `ws` library's WebSocket class, used by tests that exercise
 * RealtimeSession or TranscriptionSession without touching OpenAI.
 *
 * Behavior:
 *   - on construction, schedules an 'open' event on the next tick
 *   - records every message the unit-under-test sends, exposed via .sent
 *   - tests can drive the receive side via .emitServer({...event...})
 *   - .close() emits a 'close' event next tick
 *
 * Compatible API surface used by RealtimeSession + TranscriptionSession:
 *   - constructor(url, options)
 *   - on(event, handler)
 *   - send(payload)
 *   - close()
 *   - readyState
 *   - WebSocket.OPEN constant (static)
 *
 * Not a complete ws-mock: only what our two session classes consume.
 */

import { EventEmitter } from 'node:events';

type Handler = (...args: unknown[]) => void;

export class MockOpenAIWebSocket extends EventEmitter {
  static OPEN = 1;
  static CLOSED = 3;

  readyState = MockOpenAIWebSocket.OPEN;
  readonly url: string;
  readonly options: Record<string, unknown>;
  readonly sent: string[] = [];
  /** Set by tests; runs on every send so the fixture can react. */
  onSend?: (payload: string, mock: MockOpenAIWebSocket) => void;

  constructor(url: string, options: Record<string, unknown> = {}) {
    super();
    this.url = url;
    this.options = options;
    // 'open' must fire async — production callers register their
    // 'open' handler immediately after construction.
    queueMicrotask(() => this.emit('open'));
  }

  override on(event: string, handler: Handler): this {
    return super.on(event, handler);
  }

  send(payload: string): void {
    this.sent.push(payload);
    this.onSend?.(payload, this);
  }

  close(): void {
    this.readyState = MockOpenAIWebSocket.CLOSED;
    queueMicrotask(() => this.emit('close'));
  }

  /** Drive a server event into the unit-under-test. */
  emitServer(event: object): void {
    this.emit('message', Buffer.from(JSON.stringify(event)));
  }

  /** Convenience: only the parsed messages the unit-under-test sent. */
  sentParsed(): unknown[] {
    return this.sent.map((s) => JSON.parse(s));
  }

  /** Convenience: find the first sent message of a given top-level `type`. */
  firstSentOfType(type: string): Record<string, unknown> | undefined {
    for (const s of this.sent) {
      const obj = JSON.parse(s) as { type?: string };
      if (obj?.type === type) return obj as Record<string, unknown>;
    }
    return undefined;
  }
}
