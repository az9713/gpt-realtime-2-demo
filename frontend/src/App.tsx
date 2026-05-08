import { NavLink, Route, Routes } from 'react-router-dom';
import { AuthGate, logout } from './auth/AuthGate';
import { TalkPage } from './cockpit/TalkPage';
import { ConversationListPage } from './conversations/ConversationListPage';
import { TraceExplorerPage } from './conversations/TraceExplorerPage';
import { ApprovalQueuePage } from './approvals/ApprovalQueuePage';
import { VoicemailListPage } from './voicemails/VoicemailListPage';
import { AuditListPage } from './audit/AuditListPage';

function NavTab({ to, label }: { to: string; label: string }): JSX.Element {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `px-3 py-2 rounded-md text-sm ${
          isActive
            ? 'bg-emerald-600 text-white'
            : 'text-slate-300 hover:bg-slate-800 hover:text-white'
        }`
      }
      end
    >
      {label}
    </NavLink>
  );
}

export default function App(): JSX.Element {
  return (
    <AuthGate>
      <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
        <header className="border-b border-slate-800 px-6 py-3 flex items-center gap-6">
          <div className="font-semibold text-emerald-400">cockpit</div>
          <nav className="flex gap-1">
            <NavTab to="/" label="Talk" />
            <NavTab to="/approvals" label="Approvals" />
            <NavTab to="/voicemails" label="Voicemails" />
            <NavTab to="/audit" label="Audit" />
            <NavTab to="/conversations" label="Conversations" />
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm text-slate-400">
            <button
              type="button"
              onClick={logout}
              className="hover:text-slate-100"
            >
              Sign out
            </button>
          </div>
        </header>
        <main className="flex-1 overflow-auto">
          <Routes>
            <Route path="/" element={<TalkPage />} />
            <Route path="/approvals" element={<ApprovalQueuePage />} />
            <Route path="/voicemails" element={<VoicemailListPage />} />
            <Route path="/audit" element={<AuditListPage />} />
            <Route path="/conversations" element={<ConversationListPage />} />
            <Route path="/conversations/:id" element={<TraceExplorerPage />} />
          </Routes>
        </main>
      </div>
    </AuthGate>
  );
}
