import { useEffect, useState } from 'react';
import { api, type PendingApproval } from '../lib/api';

export function ApprovalQueuePage(): JSX.Element {
  const [items, setItems] = useState<PendingApproval[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = async (): Promise<void> => {
    try {
      const r = await api<{ approvals: PendingApproval[] }>('/v1/approvals');
      setItems(r.approvals);
    } catch (err) {
      console.error('approvals_fetch_failed', err);
    }
  };

  useEffect(() => {
    void refresh();
    const id = setInterval(refresh, 1000);
    return () => clearInterval(id);
  }, []);

  const resolve = async (id: string, decision: 'approved' | 'denied'): Promise<void> => {
    setBusy(id);
    try {
      await api(`/v1/approvals/${id}/resolve`, {
        method: 'POST',
        body: JSON.stringify({ decision, decided_by: 'cockpit-operator' }),
      });
      await refresh();
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold mb-4">Pending approvals</h1>
      {items.length === 0 ? (
        <p className="text-slate-400">No pending approvals.</p>
      ) : (
        <ul className="space-y-3">
          {items.map((a) => (
            <li
              key={a.approval_id}
              className="bg-slate-900 border border-amber-700/40 rounded-lg p-4 flex items-start gap-4"
            >
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span className="px-2 py-0.5 rounded text-xs bg-amber-700/30 text-amber-200">
                    {a.blast_radius}
                  </span>
                  <span className="font-mono text-sm text-emerald-300">
                    {a.tool_name}
                  </span>
                </div>
                <pre className="text-xs text-slate-400 mt-2 whitespace-pre-wrap font-mono">
                  {JSON.stringify(a.args, null, 2)}
                </pre>
                <div className="text-xs text-slate-500 mt-2">
                  conv {a.conversation_id.slice(0, 8)} · requested{' '}
                  {new Date(a.requested_at).toLocaleTimeString()}
                </div>
              </div>
              <div className="flex flex-col gap-2">
                <button
                  type="button"
                  disabled={busy === a.approval_id}
                  onClick={() => void resolve(a.approval_id, 'approved')}
                  className="px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-sm"
                >
                  Approve
                </button>
                <button
                  type="button"
                  disabled={busy === a.approval_id}
                  onClick={() => void resolve(a.approval_id, 'denied')}
                  className="px-3 py-1.5 rounded bg-rose-600 hover:bg-rose-500 disabled:opacity-50 text-sm"
                >
                  Deny
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
