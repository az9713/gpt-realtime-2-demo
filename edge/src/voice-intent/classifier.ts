/**
 * Voice-intent classifier (spec §13.1).
 *
 * v1 implementation is a deterministic placeholder: it accepts already-
 * recognized text from the OpenAI transcript stream and matches an exact
 * phrase per pending tool call. The classifier sits behind the `Classifier`
 * interface so a wasm-whisper or OpenAI-roundtrip variant can swap in.
 */

import type { Settings } from '../settings.js';
import type { CoreClient } from '../core-client/index.js';
import { log } from '../logging.js';

export interface Classifier {
  feed(audioBase64: string): void;
  shutdown(): void;
}

interface SessionState {
  classifier: Classifier;
}

const _state = new Map<string, SessionState>();

class NoopAudioClassifier implements Classifier {
  feed(_audioBase64: string): void {
    /* deliberate: v1 uses transcript-based matching */
  }
  shutdown(): void {
    /* noop */
  }
}

export function startVoiceIntent(
  conversationId: string,
  _settings: Settings,
  _core: CoreClient,
): void {
  if (_state.has(conversationId)) return;
  _state.set(conversationId, { classifier: new NoopAudioClassifier() });
  log.debug({ conv: conversationId }, 'voice_intent_started');
}

export function feedAudio(conversationId: string, audioBase64: string): void {
  _state.get(conversationId)?.classifier.feed(audioBase64);
}

/**
 * Called by the OpenAI transcript stream. If the recognized phrase
 * matches the pending approval phrase exactly, the core resolves it.
 */
export async function checkTranscriptForApproval(
  conversationId: string,
  transcript: string,
  core: CoreClient,
): Promise<void> {
  if (!transcript) return;
  // The core knows which phrase is pending; we forward the candidate.
  await core.approvalByVoice(conversationId, transcript.trim());
}

export function stopVoiceIntent(conversationId: string): void {
  const s = _state.get(conversationId);
  if (s) {
    s.classifier.shutdown();
    _state.delete(conversationId);
  }
}
