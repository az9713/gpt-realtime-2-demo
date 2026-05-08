export interface RealtimeSessionUpdateEvent {
  type: 'session.update';
  session: {
    instructions?: string;
    voice?: string;
    modalities?: ('text' | 'audio')[];
    tools?: unknown[];
    turn_detection?: { type: string } | null;
    input_audio_transcription?: { model: string };
  };
}

export interface RealtimeFunctionCallArgEvent {
  type: 'response.function_call_arguments.done';
  call_id: string;
  name: string;
  arguments: string;
  response_id?: string;
}

export interface RealtimeTranscriptDeltaEvent {
  type: 'response.audio_transcript.delta';
  delta: string;
  response_id?: string;
}

export interface RealtimeUserTranscriptEvent {
  type: 'conversation.item.input_audio_transcription.completed';
  transcript: string;
}

export interface RealtimeResponseDoneEvent {
  type: 'response.done';
  response: { id: string; usage?: unknown };
}

export interface RealtimeAudioDeltaEvent {
  type: 'response.audio.delta';
  delta: string; // base64
}

export type RealtimeServerEvent =
  | RealtimeFunctionCallArgEvent
  | RealtimeTranscriptDeltaEvent
  | RealtimeUserTranscriptEvent
  | RealtimeResponseDoneEvent
  | RealtimeAudioDeltaEvent
  | { type: string; [k: string]: unknown };

export interface RealtimeFunctionCallOutput {
  type: 'conversation.item.create';
  item: {
    type: 'function_call_output';
    call_id: string;
    output: string;
  };
}

export function functionCallOutput(callId: string, output: unknown): RealtimeFunctionCallOutput {
  return {
    type: 'conversation.item.create',
    item: {
      type: 'function_call_output',
      call_id: callId,
      output: typeof output === 'string' ? output : JSON.stringify(output),
    },
  };
}

export function responseCreate(): { type: 'response.create' } {
  return { type: 'response.create' };
}

export function inputAudioAppend(base64Audio: string): {
  type: 'input_audio_buffer.append';
  audio: string;
} {
  return { type: 'input_audio_buffer.append', audio: base64Audio };
}
