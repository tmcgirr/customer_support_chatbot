import { useMemo, useState } from "react";

import {
  AdminAuthError,
  createAdminClient,
  type AdminClient,
  type AdminCreds,
  type MeResponse,
} from "./api";
import Audit from "./Audit";
import Canonical from "./Canonical";
import Conversations from "./Conversations";
import Dashboard from "./Dashboard";
import KnowledgeSources from "./KnowledgeSources";
import Privacy from "./Privacy";
import Requests from "./Requests";
import Unresolved from "./Unresolved";

type Tab =
  | "dashboard"
  | "conversations"
  | "requests"
  | "knowledge"
  | "canonical"
  | "unresolved"
  | "audit"
  | "privacy";

const TABS: { id: Tab; label: string }[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "conversations", label: "Conversations" },
  { id: "requests", label: "Requests" },
  { id: "knowledge", label: "Knowledge" },
  { id: "canonical", label: "Canonical" },
  { id: "unresolved", label: "Unresolved" },
  { id: "audit", label: "Audit" },
  { id: "privacy", label: "Privacy" },
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

function Shell({
  client,
  me,
  onSignOut,
}: {
  client: AdminClient;
  me: MeResponse;
  onSignOut: () => void;
}) {
  const [tab, setTab] = useState<Tab>("dashboard");
  // Remount a view when re-selected so it re-fetches fresh data.
  const [nonce, setNonce] = useState(0);

  function selectTab(next: Tab) {
    setNonce((n) => n + 1);
    setTab(next);
  }

  const viewKey = `${tab}-${nonce}`;
  const role = me.role;

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
        <span className="admin-whoami">
          {me.username} ({role})
        </span>
        <button type="button" className="admin-signout" onClick={onSignOut}>
          Sign out
        </button>
      </header>

      <main className="admin-main">
        {tab === "dashboard" && (
          <Dashboard key={viewKey} client={client} onAuthError={onSignOut} />
        )}
        {tab === "conversations" && (
          <Conversations key={viewKey} client={client} role={role} onAuthError={onSignOut} />
        )}
        {tab === "requests" && (
          <Requests key={viewKey} client={client} role={role} onAuthError={onSignOut} />
        )}
        {tab === "knowledge" && (
          <KnowledgeSources key={viewKey} client={client} role={role} onAuthError={onSignOut} />
        )}
        {tab === "canonical" && (
          <Canonical key={viewKey} client={client} role={role} onAuthError={onSignOut} />
        )}
        {tab === "unresolved" && (
          <Unresolved key={viewKey} client={client} onAuthError={onSignOut} />
        )}
        {tab === "audit" && <Audit key={viewKey} client={client} onAuthError={onSignOut} />}
        {tab === "privacy" && (
          <Privacy key={viewKey} client={client} role={role} onAuthError={onSignOut} />
        )}
      </main>
    </div>
  );
}

export default function AdminApp() {
  // Credentials + identity live only in memory (never localStorage).
  const [creds, setCreds] = useState<AdminCreds | null>(null);
  const [me, setMe] = useState<MeResponse | null>(null);

  const client = useMemo(() => (creds ? createAdminClient(creds) : null), [creds]);

  async function authenticate(candidate: AdminCreds) {
    // Verify by calling /me; a 401 throws AdminAuthError (surfaced by Login as
    // "Invalid admin credentials.") and the response gives us the role so we
    // can gate admin-only actions.
    const probe = createAdminClient(candidate);
    const identity = await probe.getMe();
    setMe(identity);
    setCreds(candidate);
  }

  function signOut() {
    setCreds(null);
    setMe(null);
  }

  if (!creds || !client || !me) {
    return <Login onAuthenticate={authenticate} />;
  }

  return <Shell client={client} me={me} onSignOut={signOut} />;
}
