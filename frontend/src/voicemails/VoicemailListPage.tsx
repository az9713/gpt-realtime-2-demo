import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, type ConversationRow } from '../lib/api';

export function VoicemailListPage(): JSX.Element {
  const [rows, setRows] = useState<ConversationRow[]>([]);

  useEffect(() => {
    let cancelled = false;
    const refresh = (): void => {
      void api<{ conversations: ConversationRow[] }>(
        '/v1/conversations?limit=50&mode=voicemail',
      ).then((r) => {
        if (!cancelled) setRows(r.conversations);
      });
    };
    refresh();
    const ix = setInterval(refresh, 5000);
    return () => {
      cancelled = true;
      clearInterval(ix);
    };
  }, []);

  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold mb-4">Voicemails</h1>
      <p className="text-slate-400 mb-6 max-w-2xl text-sm">
        Calls captured outside business hours. Each row is a recorded
        message — open it to read the transcript and the extracted
        intent.
      </p>
      {rows.length === 0 ? (
        <p className="text-slate-500">No voicemails yet.</p>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-left text-slate-400">
            <tr>
              <th className="py-2 pr-4">Received</th>
              <th className="py-2 pr-4">Vertical</th>
              <th className="py-2 pr-4">Language</th>
              <th className="py-2 pr-4">Duration</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const dur =
                r.ended_at && r.started_at
                  ? Math.round(
                      (new Date(r.ended_at).getTime() - new Date(r.started_at).getTime()) / 1000,
                    )
                  : null;
              return (
                <tr key={r.id} className="border-t border-slate-800 hover:bg-slate-900">
                  <td className="py-2 pr-4 font-mono">
                    <Link
                      to={`/conversations/${r.id}`}
                      className="text-amber-400 hover:underline"
                    >
                      {new Date(r.started_at).toLocaleString()}
                    </Link>
                  </td>
                  <td className="py-2 pr-4">{r.vertical}</td>
                  <td className="py-2 pr-4">{r.language ?? '—'}</td>
                  <td className="py-2 pr-4 text-slate-400">
                    {dur != null ? `${dur}s` : 'live'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
