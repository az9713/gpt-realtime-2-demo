import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';

interface Divergence {
  id: string;
  conversation_id: string;
  agent_turn_id: string | null;
  canonical_turn_id: string | null;
  kind: 'paraphrase' | 'omission' | 'addition' | 'mismatch';
  score: string;
  agent_text: string | null;
  canonical_text: string | null;
  flagged_at: string;
}

const KIND_COLOR: Record<Divergence['kind'], string> = {
  paraphrase: 'bg-slate-700',
  omission: 'bg-amber-700',
  addition: 'bg-amber-700',
  mismatch: 'bg-rose-700',
};

export function AuditListPage(): JSX.Element {
  const [rows, setRows] = useState<Divergence[]>([]);

  useEffect(() => {
    let cancelled = false;
    const refresh = (): void => {
      void api<{ divergences: Divergence[] }>('/v1/audits/divergences?limit=100').then((r) => {
        if (!cancelled) setRows(r.divergences);
      });
    };
    refresh();
    const ix = setInterval(refresh, 10_000);
    return () => {
      cancelled = true;
      clearInterval(ix);
    };
  }, []);

  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold mb-4">Audit divergences</h1>
      <p className="text-slate-400 mb-6 max-w-3xl text-sm">
        Each row is a place where the agent's transcript disagreed with the
        canonical whisper transcript on the same utterance. The
        <code className="px-1 mx-1 bg-slate-800 rounded">make audit</code>
        nightly job populates this table.
      </p>
      {rows.length === 0 ? (
        <p className="text-slate-500">No divergences yet.</p>
      ) : (
        <ul className="space-y-3">
          {rows.map((d) => (
            <li
              key={d.id}
              className="bg-slate-900 border border-slate-800 rounded-lg p-4"
            >
              <div className="flex items-center gap-2 mb-2">
                <span
                  className={`text-xs uppercase tracking-wide px-2 py-1 rounded text-white ${KIND_COLOR[d.kind]}`}
                >
                  {d.kind}
                </span>
                <span className="text-xs text-slate-500 font-mono">
                  WER {Number(d.score).toFixed(2)}
                </span>
                <Link
                  to={`/conversations/${d.conversation_id}`}
                  className="text-xs text-emerald-400 hover:underline ml-auto"
                >
                  conv {d.conversation_id.slice(0, 8)}
                </Link>
                <span className="text-xs text-slate-500">
                  {new Date(d.flagged_at).toLocaleString()}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <div className="text-xs text-slate-500 mb-1">Agent transcript</div>
                  <div className="bg-slate-800 rounded p-2 text-slate-200">
                    {d.agent_text ?? <span className="text-slate-500 italic">(none)</span>}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">Canonical (whisper)</div>
                  <div className="bg-slate-800 rounded p-2 text-slate-200">
                    {d.canonical_text ?? <span className="text-slate-500 italic">(none)</span>}
                  </div>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
