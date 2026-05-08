export function ModeBadge({ mode }: { mode: 'realtime2' | 'translate' }): JSX.Element {
  const label = mode === 'realtime2' ? 'Realtime-2' : 'Translate';
  const cls = mode === 'realtime2' ? 'bg-emerald-600' : 'bg-indigo-600';
  return (
    <span className={`text-xs uppercase tracking-wide px-2 py-1 rounded ${cls} text-white`}>
      {label}
    </span>
  );
}
