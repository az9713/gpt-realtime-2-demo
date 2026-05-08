interface Props {
  mode: 'realtime2' | 'translate';
  onToggle: () => void | Promise<void>;
  disabled?: boolean;
}

export function ModeToggle({ mode, onToggle, disabled }: Props): JSX.Element {
  return (
    <button
      type="button"
      onClick={() => void onToggle()}
      disabled={disabled}
      className="px-3 py-1.5 rounded-md text-xs border border-slate-700 hover:border-emerald-500 disabled:opacity-50"
    >
      {mode === 'realtime2' ? 'Switch to Translate' : 'Switch to Realtime'}
    </button>
  );
}
