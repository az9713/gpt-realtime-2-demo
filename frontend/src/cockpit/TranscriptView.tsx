export interface TranscriptLine {
  role: 'user' | 'agent' | 'system' | 'tool';
  text: string;
  partial?: boolean;
}

const ROLE_STYLE: Record<TranscriptLine['role'], string> = {
  user: 'bg-slate-800/60 border-slate-700',
  agent: 'bg-emerald-900/30 border-emerald-800',
  tool: 'bg-amber-900/30 border-amber-800',
  system: 'bg-slate-800/40 border-slate-700 text-slate-400',
};

export function TranscriptView({ lines }: { lines: TranscriptLine[] }): JSX.Element {
  return (
    <div className="flex-1 overflow-auto space-y-2 pr-2">
      {lines.map((l, i) => (
        <div
          key={i}
          className={`border rounded-md p-3 text-sm ${ROLE_STYLE[l.role]}`}
        >
          <div className="text-xs uppercase tracking-wider text-slate-500 mb-1">
            {l.role}
            {l.partial && <span className="ml-2 text-slate-600">…</span>}
          </div>
          <div className="text-slate-100 whitespace-pre-wrap">{l.text}</div>
        </div>
      ))}
    </div>
  );
}
