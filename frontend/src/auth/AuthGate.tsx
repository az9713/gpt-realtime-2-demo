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
  // Auth disabled for local dev — always pass through
  return <>{children}</>;
}
