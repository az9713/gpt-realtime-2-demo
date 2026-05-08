import type { RealtimeSession } from './session.js';

const _registry = new Map<string, RealtimeSession>();

export function registerSession(session: RealtimeSession): void {
  _registry.set(session.conversationId, session);
}

export function getSession(conversationId: string): RealtimeSession | undefined {
  return _registry.get(conversationId);
}

export function dropSession(conversationId: string): void {
  _registry.delete(conversationId);
}
