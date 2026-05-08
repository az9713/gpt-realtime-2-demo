import { useEffect, useState } from 'react';

const STORAGE_KEY = 'cockpit.auth.basic';

export function isAuthed(): boolean {
  return typeof window !== 'undefined' && Boolean(window.sessionStorage.getItem(STORAGE_KEY));
}

export function logout(): void {
  window.sessionStorage.removeItem(STORAGE_KEY);
  window.location.reload();
}

interface Props {
  children: React.ReactNode;
}

export function AuthGate({ children }: Props): JSX.Element {
  const [ready, setReady] = useState(isAuthed());
  const [user, setUser] = useState('');
  const [pw, setPw] = useState('');
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (ready) return;
  }, [ready]);

  if (ready) return <>{children}</>;

  const expectedUser = (import.meta.env.VITE_OPERATOR_USER as string | undefined) ?? 'operator';
  const expectedPw = (import.meta.env.VITE_OPERATOR_PASSWORD as string | undefined) ?? 'change-me';

  const submit = (e: React.FormEvent): void => {
    e.preventDefault();
    if (user === expectedUser && pw === expectedPw) {
      window.sessionStorage.setItem(STORAGE_KEY, '1');
      setReady(true);
    } else {
      setErr('Invalid credentials');
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-950 text-slate-100">
      <form
        onSubmit={submit}
        className="bg-slate-900 border border-slate-800 rounded-lg p-8 w-96 space-y-4"
      >
        <h1 className="text-2xl font-semibold">Cockpit Login</h1>
        <p className="text-sm text-slate-400">Voice Operations Cockpit · v1</p>
        <input
          className="w-full bg-slate-800 border border-slate-700 rounded p-2"
          placeholder="username"
          value={user}
          onChange={(e) => setUser(e.target.value)}
          autoFocus
        />
        <input
          className="w-full bg-slate-800 border border-slate-700 rounded p-2"
          type="password"
          placeholder="password"
          value={pw}
          onChange={(e) => setPw(e.target.value)}
        />
        {err && <p className="text-rose-400 text-sm">{err}</p>}
        <button
          type="submit"
          className="w-full bg-emerald-600 hover:bg-emerald-500 rounded p-2 font-medium"
        >
          Sign in
        </button>
      </form>
    </div>
  );
}
