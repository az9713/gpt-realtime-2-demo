type Mode = 'realtime2' | 'translate' | 'notetaker' | 'voicemail';

const LABEL: Record<Mode, string> = {
  realtime2: 'Realtime-2',
  translate: 'Translate',
  notetaker: 'Notes only',
  voicemail: 'Voicemail',
};

const COLOR: Record<Mode, string> = {
  realtime2: 'bg-emerald-600',
  translate: 'bg-indigo-600',
  notetaker: 'bg-slate-600',
  voicemail: 'bg-amber-700',
};

export function ModeBadge({ mode }: { mode: Mode }): JSX.Element {
  return (
    <span
      className={`text-xs uppercase tracking-wide px-2 py-1 rounded ${COLOR[mode]} text-white`}
    >
      {LABEL[mode]}
    </span>
  );
}
