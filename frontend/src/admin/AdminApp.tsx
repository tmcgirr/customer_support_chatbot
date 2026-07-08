import { useMemo, useState } from "react";

import { AdminAuthError, createAdminClient, type AdminClient, type AdminCreds } from "./api";
import Conversations from "./Conversations";
import Dashboard from "./Dashboard";
import Requests from "./Requests";
import Unresolved from "./Unresolved";

type Tab = "dashboard" | "conversations" | "requests" | "unresolved";

const TABS: { id: Tab; label: string }[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "conversations", label: "Conversations" },
  { id: "requests", label: "Requests" },
  { id: "unresolved", label: "Unresolved" },
];

function Login({ onAuthenticate }: { onAuthenticate: (creds: AdminCreds) => Promise<void> }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onAuthenticate({ username, password });
    } catch (err: unknown) {
      if (err instanceof AdminAuthError) {
        setError("Invalid admin credentials.");
      } else {
        setError(err instanceof Error ? err.message : "Something went wrong.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="admin-login">
      <form onSubmit={handleSubmit}>
        <h1>Cadre AI — Admin</h1>
        <label>
          Username
          <input
            type="text"
            value={username}
            autoComplete="username"
            onChange={(e) => setUsername(e.target.value)}
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            autoComplete="current-password"
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && <p className="admin-error">{error}</p>}
        <button type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}

function Shell({ client, onSignOut }: { client: AdminClient; onSignOut: () => void }) {
  const [tab, setTab] = useState<Tab>("dashboard");
  // Remount a view when re-selected so it re-fetches fresh data.
  const [nonce, setNonce] = useState(0);

  function selectTab(next: Tab) {
    setNonce((n) => n + 1);
    setTab(next);
  }

  const viewKey = `${tab}-${nonce}`;

  return (
    <div className="admin-shell">
      <header className="admin-header">
        <strong>Cadre AI — Admin</strong>
        <nav className="admin-nav">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              className={t.id === tab ? "admin-tab admin-tab-active" : "admin-tab"}
              onClick={() => selectTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <button type="button" className="admin-signout" onClick={onSignOut}>
          Sign out
        </button>
      </header>

      <main className="admin-main">
        {tab === "dashboard" && (
          <Dashboard key={viewKey} client={client} onAuthError={onSignOut} />
        )}
        {tab === "conversations" && (
          <Conversations key={viewKey} client={client} onAuthError={onSignOut} />
        )}
        {tab === "requests" && <Requests key={viewKey} client={client} onAuthError={onSignOut} />}
        {tab === "unresolved" && (
          <Unresolved key={viewKey} client={client} onAuthError={onSignOut} />
        )}
      </main>
    </div>
  );
}

export default function AdminApp() {
  // Credentials live only in memory (never localStorage).
  const [creds, setCreds] = useState<AdminCreds | null>(null);

  const client = useMemo(() => (creds ? createAdminClient(creds) : null), [creds]);

  async function authenticate(candidate: AdminCreds) {
    // Verify by making one authenticated call; a 401 throws AdminAuthError,
    // which Login surfaces as "Invalid admin credentials."
    const probe = createAdminClient(candidate);
    await probe.getDashboard();
    setCreds(candidate);
  }

  if (!creds || !client) {
    return <Login onAuthenticate={authenticate} />;
  }

  return <Shell client={client} onSignOut={() => setCreds(null)} />;
}
