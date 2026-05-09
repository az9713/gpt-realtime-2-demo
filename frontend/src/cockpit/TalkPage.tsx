import { useEffect, useRef, useState } from 'react';
import { ModeBadge } from './ModeBadge';
import { ModeToggle } from './ModeToggle';
import { TranscriptView, type TranscriptLine } from './TranscriptView';

type SessionMode = 'realtime2' | 'translate' | 'notetaker';

interface SessionInfo {
  conversationId: string;
  vertical: string;
  mode: SessionMode;
}

const SAMPLE_RATE = 24_000;

export function TalkPage(): JSX.Element {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [lines, setLines] = useState<TranscriptLine[]>([]);
  const [recording, setRecording] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const playerCtxRef = useRef<AudioContext | null>(null);
  const playbackTimeRef = useRef<number>(0);

  const append = (line: TranscriptLine): void => {
    setLines((cur) => {
      const last = cur[cur.length - 1];
      if (last && last.role === line.role && line.role === 'agent' && last.partial) {
        const merged = { ...last, text: last.text + line.text, partial: line.partial };
        return [...cur.slice(0, -1), merged];
      }
      return [...cur, line];
    });
  };

  const start = async (sessionMode: SessionMode = 'realtime2'): Promise<void> => {
    setLines([]);
    const edgeBase = ((import.meta.env.VITE_EDGE_URL as string | undefined) ??
      'http://localhost:8080').replace(/^http/, 'ws');
    const params = new URLSearchParams({ vertical: 'hvac', mode: sessionMode });
    const wsUrl = `${edgeBase}/v1/voice/browser?${params.toString()}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = (ev) => {
      if (wsRef.current !== ws) return;
      const data = JSON.parse(ev.data);
      switch (data.kind) {
        case 'session.created':
          setSession({
            conversationId: data.conversation_id,
            vertical: data.vertical,
            mode: data.mode,
          });
          return;
        case 'transcript.user':
          append({ role: 'user', text: data.text, partial: false });
          return;
        case 'transcript.delta':
          append({ role: 'agent', text: data.text, partial: true });
          return;
        case 'response.done':
          setLines((cur) => cur.map((l) => ({ ...l, partial: false })));
          return;
        case 'audio.delta':
          enqueueAgentAudio(data.audio);
          return;
        case 'session.closed':
          setRecording(false);
          return;
        default:
          return;
      }
    };

    ws.onopen = async () => {
      ws.send(JSON.stringify({ kind: 'hello' }));
      await openMic(ws);
      setRecording(true);
    };
  };

  const stop = (): void => {
    const ws = wsRef.current;
    wsRef.current = null;
    if (ws) {
      ws.onmessage = null;
      ws.onopen = null;
      try {
        if (ws.readyState === ws.OPEN) ws.send(JSON.stringify({ kind: 'end' }));
      } catch {
        /* ignore */
      }
      try {
        ws.close();
      } catch {
        /* ignore */
      }
    }
    closeMic();
    closePlayer();
    setRecording(false);
    setSession(null);
  };

  const openMic = async (ws: WebSocket): Promise<void> => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
    audioCtxRef.current = ctx;
    const source = ctx.createMediaStreamSource(stream);
    sourceRef.current = source;
    const processor = ctx.createScriptProcessor(4096, 1, 1);
    processorRef.current = processor;
    source.connect(processor);
    processor.connect(ctx.destination);
    processor.onaudioprocess = (event) => {
      if (ws.readyState !== ws.OPEN) return;
      const playerCtx = playerCtxRef.current;
      if (playerCtx && playbackTimeRef.current > playerCtx.currentTime + 0.05) {
        return;
      }
      const input = event.inputBuffer.getChannelData(0);
      const pcm = new Int16Array(input.length);
      for (let i = 0; i < input.length; i++) {
        const s = Math.max(-1, Math.min(1, input[i]));
        pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      }
      const buf = new Uint8Array(pcm.buffer);
      const b64 = btoa(String.fromCharCode(...buf));
      ws.send(JSON.stringify({ kind: 'audio.append', audio: b64 }));
    };
    // Server-side semantic_vad commits the audio buffer and creates the
    // response automatically. A manual commit timer would race with VAD and
    // double-fire response.create, looping the agent on the same fragment.
  };

  const closeMic = (): void => {
    if (processorRef.current) {
      processorRef.current.onaudioprocess = null;
      processorRef.current.disconnect();
    }
    sourceRef.current?.disconnect();
    audioCtxRef.current?.close().catch(() => undefined);
    processorRef.current = null;
    sourceRef.current = null;
    audioCtxRef.current = null;
  };

  const closePlayer = (): void => {
    const ctx = playerCtxRef.current;
    playerCtxRef.current = null;
    playbackTimeRef.current = 0;
    if (ctx) ctx.close().catch(() => undefined);
  };

  const enqueueAgentAudio = (b64: string): void => {
    if (!wsRef.current) return;
    if (!playerCtxRef.current) {
      playerCtxRef.current = new AudioContext({ sampleRate: SAMPLE_RATE });
      playbackTimeRef.current = playerCtxRef.current.currentTime;
    }
    const ctx = playerCtxRef.current;
    if (ctx.state === 'closed') return;
    const bytes = atob(b64);
    const pcm = new Int16Array(bytes.length / 2);
    for (let i = 0; i < pcm.length; i++) {
      pcm[i] = (bytes.charCodeAt(i * 2 + 1) << 8) | bytes.charCodeAt(i * 2);
    }
    const buffer = ctx.createBuffer(1, pcm.length, SAMPLE_RATE);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) channel[i] = pcm[i] / 0x8000;
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(ctx.destination);
    const startAt = Math.max(ctx.currentTime, playbackTimeRef.current);
    src.start(startAt);
    playbackTimeRef.current = startAt + buffer.duration;
  };

  const toggleMode = async (): Promise<void> => {
    if (!session) return;
    const next = session.mode === 'realtime2' ? 'translate' : 'realtime2';
    wsRef.current?.send(JSON.stringify({ kind: 'mode.switch', mode: next }));
    setSession({ ...session, mode: next });
  };

  useEffect(() => () => stop(), []); // cleanup on unmount

  return (
    <div className="p-6 grid grid-cols-3 gap-4 h-full">
      <section className="col-span-2 flex flex-col bg-slate-900 border border-slate-800 rounded-lg p-4">
        <div className="flex items-center gap-3 mb-4">
          <button
            type="button"
            onClick={recording ? stop : () => void start('realtime2')}
            className={`px-4 py-2 rounded-md font-medium ${
              recording
                ? 'bg-rose-600 hover:bg-rose-500'
                : 'bg-emerald-600 hover:bg-emerald-500'
            }`}
          >
            {recording ? 'Stop' : 'Talk'}
          </button>
          {!recording && (
            <button
              type="button"
              onClick={() => void start('notetaker')}
              className="px-4 py-2 rounded-md font-medium border border-slate-600 text-slate-200 hover:bg-slate-800"
              title="Silent transcription only — no agent persona, no tools"
            >
              Notes only
            </button>
          )}
          {session && <ModeBadge mode={session.mode} />}
          {session && session.mode !== 'notetaker' && (
            <ModeToggle mode={session.mode} onToggle={toggleMode} />
          )}
          {session && (
            <span className="text-xs text-slate-500 font-mono">
              {session.conversationId.slice(0, 8)} · {session.vertical}
            </span>
          )}
        </div>
        <TranscriptView lines={lines} />
      </section>
      <aside className="bg-slate-900 border border-slate-800 rounded-lg p-4 text-sm text-slate-400">
        <h2 className="text-slate-100 font-semibold mb-2">Live session</h2>
        <p>
          Press Talk and grant microphone access. Audio streams over WebSocket
          to the edge; the edge bridges to the OpenAI Realtime API and dispatches
          tool calls into the Python agent core.
        </p>
        <p className="mt-3">
          Approvals appear in the Approvals tab and are also resolvable by the
          spoken phrase configured in the active vertical pack.
        </p>
      </aside>
    </div>
  );
}
