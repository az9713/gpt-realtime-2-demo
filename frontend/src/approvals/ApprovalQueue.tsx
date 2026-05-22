import { useEffect, useState } from 'react';
import { api, type PendingApproval } from '../lib/api';

interface ApprovalQueueProps {
  /** Render in compact mode (for sidebar embedding) */
  compact?: boolean;
  /** Only show approvals for this conversation */
  conversationId?: string;
}

export function ApprovalQueue({
  compact = false,
  conversationId,
}: ApprovalQueueProps): JSX.Element {
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

    const wsUrl =
      (window.location.protocol === 'https:' ? 'wss:' : 'ws:') +
      '//' +
      window.location.host +
      '/v1/approvals/events';

    let ws: WebSocket | null = null;
    let reconnectTimer: number | undefined;

    const connect = () => {
      ws = new WebSocket(wsUrl);
      ws.onmessage = () => {
        void refresh();
      };
      ws.onclose = () => {
        reconnectTimer = window.setTimeout(connect, 2000);
      };
    };

    connect();

    return () => {
      clearTimeout(reconnectTimer);
      if (ws) {
        ws.onclose = null;
        ws.close();
      }
    };
  }, []);

  const resolve = async (
    id: string,
    decision: 'approved' | 'denied',
  ): Promise<void> => {
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

  const filtered = conversationId
    ? items.filter((a) => a.conversation_id === conversationId)
    : items;

  if (filtered.length === 0) {
    return (
      <div className={compact ? 'text-xs text-slate-500' : 'p-6'}>
        <p className="text-slate-400">
          {compact ? 'No pending approvals' : 'No pending approvals.'}
        </p>
      </div>
    );
  }

  return (
    <ul className={compact ? 'space-y-2' : 'space-y-3'}>
      {filtered.map((a) => (
        <li
          key={a.approval_id}
          className={`border border-amber-700/40 rounded-lg flex items-start gap-3 ${
            compact
              ? 'bg-slate-900/80 p-2.5 text-xs'
              : 'bg-slate-900 p-4'
          }`}
        >
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span
                className={`px-1.5 py-0.5 rounded bg-amber-700/30 text-amber-200 ${
                  compact ? 'text-[10px]' : 'text-xs'
                }`}
              >
                {a.blast_radius}
              </span>
              <span
                className={`font-mono text-emerald-300 truncate ${
                  compact ? 'text-xs' : 'text-sm'
                }`}
              >
                {a.tool_name}
              </span>
            </div>
            {!compact && (
              <pre className="text-xs text-slate-400 mt-2 whitespace-pre-wrap font-mono">
                {JSON.stringify(a.args, null, 2)}
              </pre>
            )}
            <div className="text-xs text-slate-500 mt-1.5">
              conv {a.conversation_id.slice(0, 8)} ·{' '}
              {new Date(a.requested_at).toLocaleTimeString()}
              {a.timeout_seconds && (
                <span className="text-slate-600">
                  {' '}
                  · {a.timeout_seconds}s timeout
                </span>
              )}
            </div>
          </div>
          <div className={`flex gap-1.5 ${compact ? 'flex-row' : 'flex-col'}`}>
            <button
              type="button"
              disabled={busy === a.approval_id}
              onClick={() => void resolve(a.approval_id, 'approved')}
              className={`px-2 py-1 rounded bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 ${
                compact ? 'text-xs' : 'text-sm'
              }`}
            >
              Approve
            </button>
            <button
              type="button"
              disabled={busy === a.approval_id}
              onClick={() => void resolve(a.approval_id, 'denied')}
              className={`px-2 py-1 rounded bg-rose-600 hover:bg-rose-500 disabled:opacity-50 ${
                compact ? 'text-xs' : 'text-sm'
              }`}
            >
              Deny
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}
