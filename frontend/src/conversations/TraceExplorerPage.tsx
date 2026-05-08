import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { api, type ConversationRow, type TraceEvent, type TurnRow } from '../lib/api';

const KIND_COLOR: Record<string, string> = {
  'session.start': 'bg-slate-700',
  'session.end': 'bg-slate-700',
  'turn.user': 'bg-blue-700',
  'turn.agent': 'bg-emerald-700',
  'turn.tool': 'bg-amber-700',
  'tool.requested': 'bg-amber-700',
  'tool.executed': 'bg-emerald-700',
  'tool.failed': 'bg-rose-700',
  'approval.requested': 'bg-orange-700',
  'approval.resolved': 'bg-orange-600',
  'guardrail.blocked': 'bg-rose-700',
  'guardrail.passed': 'bg-slate-700',
  'mode.switch': 'bg-indigo-700',
};

export function TraceExplorerPage(): JSX.Element {
  const { id } = useParams<{ id: string }>();
  const [conv, setConv] = useState<ConversationRow | null>(null);
  const [turns, setTurns] = useState<TurnRow[]>([]);
  const [events, setEvents] = useState<TraceEvent[]>([]);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    const refresh = async (): Promise<void> => {
      const [c, t, e] = await Promise.all([
        api<ConversationRow>(`/v1/conversations/${id}`),
        api<{ turns: TurnRow[] }>(`/v1/conversations/${id}/turns`),
        api<{ events: TraceEvent[] }>(`/v1/conversations/${id}/trace`),
      ]);
      if (cancelled) return;
      setConv(c);
      setTurns(t.turns);
      setEvents(e.events);
    };
    void refresh();
    const ix = setInterval(refresh, 2000);
    return () => {
      cancelled = true;
      clearInterval(ix);
    };
  }, [id]);

  if (!conv) return <div className="p-6 text-slate-400">Loading…</div>;

  return (
    <div className="p-6 grid grid-cols-2 gap-6">
      <section>
        <h2 className="text-lg font-semibold mb-3">Trace</h2>
        <ul className="space-y-1">
          {events.map((e) => (
            <li
              key={e.id}
              className="flex items-center gap-2 text-xs font-mono"
            >
              <span className="text-slate-500 w-24">
                {new Date(e.ts).toLocaleTimeString()}
              </span>
              <span
                className={`px-2 py-0.5 rounded text-white ${
                  KIND_COLOR[e.kind] ?? 'bg-slate-700'
                }`}
              >
                {e.kind}
              </span>
              <span className="text-slate-300 truncate">
                {JSON.stringify(e.payload)}
              </span>
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h2 className="text-lg font-semibold mb-3">Turns</h2>
        <ul className="space-y-2">
          {turns.map((t) => (
            <li
              key={t.id}
              className="bg-slate-900 border border-slate-800 rounded p-3 text-sm"
            >
              <div className="text-xs uppercase tracking-wider text-slate-500 mb-1">
                {t.role}
                {t.latency_ms != null && (
                  <span className="ml-2 text-slate-600">{t.latency_ms} ms</span>
                )}
              </div>
              <div className="whitespace-pre-wrap">{t.transcript}</div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
