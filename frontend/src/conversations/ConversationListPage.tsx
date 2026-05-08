import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, type ConversationRow } from '../lib/api';

export function ConversationListPage(): JSX.Element {
  const [rows, setRows] = useState<ConversationRow[]>([]);

  useEffect(() => {
    void api<{ conversations: ConversationRow[] }>('/v1/conversations?limit=50').then((r) =>
      setRows(r.conversations),
    );
  }, []);

  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold mb-4">Recent conversations</h1>
      <table className="w-full text-sm">
        <thead className="text-left text-slate-400">
          <tr>
            <th className="py-2 pr-4">Started</th>
            <th className="py-2 pr-4">Vertical</th>
            <th className="py-2 pr-4">Surface</th>
            <th className="py-2 pr-4">Mode</th>
            <th className="py-2 pr-4">Cost</th>
            <th className="py-2 pr-4">Ended</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-t border-slate-800 hover:bg-slate-900">
              <td className="py-2 pr-4 font-mono">
                <Link to={`/conversations/${r.id}`} className="text-emerald-400 hover:underline">
                  {new Date(r.started_at).toLocaleString()}
                </Link>
              </td>
              <td className="py-2 pr-4">{r.vertical}</td>
              <td className="py-2 pr-4">{r.surface}</td>
              <td className="py-2 pr-4">{r.mode}</td>
              <td className="py-2 pr-4">${r.cost_usd}</td>
              <td className="py-2 pr-4 text-slate-400">
                {r.ended_at ? new Date(r.ended_at).toLocaleString() : 'live'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
