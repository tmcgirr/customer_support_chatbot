import { useEffect, useMemo, useRef, useState } from "react";

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
import Funnel from "./Funnel";
import { Icon } from "./icons";
import Insights from "./Insights";
import KnowledgeSources from "./KnowledgeSources";
import ModelProvider from "./ModelProvider";
import Privacy from "./Privacy";
import Requests from "./Requests";
import Unresolved from "./Unresolved";
import Usage from "./Usage";

type Tab =
  | "dashboard"
  | "insights"
  | "funnel"
  | "conversations"
  | "requests"
  | "knowledge"
  | "canonical"
  | "unresolved"
  | "audit"
  | "privacy"
  | "model"
  | "usage";

type NavItem = { id: Tab; label: string; icon: string; group: "Overview" | "Content" | "Governance" };

const NAV: NavItem[] = [
  { id: "dashboard", label: "Dashboard", icon: "dashboard", group: "Overview" },
  { id: "insights", label: "Insights", icon: "insights", group: "Overview" },
  { id: "funnel", label: "Funnel", icon: "funnel", group: "Overview" },
  { id: "conversations", label: "Conversations", icon: "conversations", group: "Overview" },
  { id: "requests", label: "Requests", icon: "requests", group: "Content" },
  { id: "knowledge", label: "Knowledge", icon: "knowledge", group: "Content" },
  { id: "canonical", label: "Canonical", icon: "canonical", group: "Content" },
  { id: "unresolved", label: "Unresolved", icon: "unresolved", group: "Content" },
  { id: "audit", label: "Audit", icon: "audit", group: "Governance" },
  { id: "privacy", label: "Privacy", icon: "privacy", group: "Governance" },
  { id: "model", label: "Model provider", icon: "model", group: "Governance" },
  { id: "usage", label: "Usage & cost", icon: "cost", group: "Governance" },
];

const GROUPS: NavItem["group"][] = ["Overview", "Content", "Governance"];

// Session persistence (per-tab). Held in sessionStorage — survives a browser
// refresh, auto-cleared when the tab closes, and NEVER localStorage. This is a
// deliberate relaxation of "creds in memory only" for admin usability (see
// docs/DECISIONS_LOG.md, 2026-07-09). Basic-auth creds only; no PII.
const CREDS_KEY = "cadre_admin_creds";

function loadStoredCreds(): AdminCreds | null {
  try {
    const raw = sessionStorage.getItem(CREDS_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<AdminCreds>;
    if (typeof parsed.username === "string" && typeof parsed.password === "string") {
      return { username: parsed.username, password: parsed.password };
    }
  } catch {
    // Corrupt/blocked storage — fall back to the login screen.
  }
  return null;
}

function storeCreds(creds: AdminCreds): void {
  try {
    sessionStorage.setItem(CREDS_KEY, JSON.stringify(creds));
  } catch {
    // Storage blocked (private mode / disabled) — session just won't persist.
  }
}

function clearStoredCreds(): void {
  try {
    sessionStorage.removeItem(CREDS_KEY);
  } catch {
    // Ignore — nothing persisted.
  }
}

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
      <div className="admin-login-brand">
        <span className="admin-brand-mark" aria-hidden>
          <Icon name="spark" size={20} />
        </span>
        <h1>Cadre AI — Admin</h1>
      </div>
      <form onSubmit={handleSubmit}>
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

function Sidebar({ tab, onSelect }: { tab: Tab; onSelect: (next: Tab) => void }) {
  return (
    <aside className="admin-sidebar">
      <div className="admin-brand">
        <span className="admin-brand-mark" aria-hidden>
          <Icon name="spark" size={19} />
        </span>
        <span className="admin-brand-text">
          <span className="admin-brand-name">Cadre AI</span>
          <span className="admin-brand-sub">Admin</span>
        </span>
      </div>

      <nav className="admin-nav" aria-label="Admin sections">
        {GROUPS.map((group) => (
          <div key={group}>
            <div className="admin-nav-label">{group}</div>
            {NAV.filter((n) => n.group === group).map((n) => (
              <button
                key={n.id}
                type="button"
                className={n.id === tab ? "admin-navitem is-active" : "admin-navitem"}
                aria-current={n.id === tab ? "page" : undefined}
                onClick={() => onSelect(n.id)}
              >
                <span className="admin-navitem-icon">
                  <Icon name={n.icon} />
                </span>
                <span className="admin-navitem-text">{n.label}</span>
              </button>
            ))}
          </div>
        ))}
      </nav>

      <div className="admin-sidebar-foot">Cadre AI · V1</div>
    </aside>
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
  // Bumping this remounts the active view, which re-runs its data fetch. Driven by
  // tab (re)selection, the Refresh button, and regaining browser-tab focus.
  const [nonce, setNonce] = useState(0);
  const lastRefreshRef = useRef(0);

  function bumpRefresh() {
    lastRefreshRef.current = Date.now();
    setNonce((n) => n + 1);
  }

  function selectTab(next: Tab) {
    bumpRefresh();
    setTab(next);
  }

  // Refetch when the operator returns to the tab (throttled so a quick blur/focus
  // or an adjacent manual refresh doesn't double-fetch).
  useEffect(() => {
    function onVisible() {
      if (document.visibilityState === "hidden") return;
      if (Date.now() - lastRefreshRef.current < 3000) return;
      bumpRefresh();
    }
    window.addEventListener("focus", onVisible);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener("focus", onVisible);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  const viewKey = `${tab}-${nonce}`;
  const role = me.role;
  const title = NAV.find((n) => n.id === tab)?.label ?? "Dashboard";

  return (
    <div className="admin-shell">
      <Sidebar tab={tab} onSelect={selectTab} />

      <div className="admin-content-col">
        <header className="admin-topbar">
          <span className="admin-topbar-title">{title}</span>
          <span className="admin-topbar-spacer" />
          <span className="admin-search" aria-hidden>
            <Icon name="search" size={16} />
            Search
          </span>
          <button
            type="button"
            className="admin-refresh"
            onClick={bumpRefresh}
            title="Refresh data"
          >
            <Icon name="refresh" size={15} />
            Refresh
          </button>
          <span className="admin-user">
            <span className="admin-avatar" aria-hidden>
              {me.username.slice(0, 1)}
            </span>
            <span className="admin-whoami">
              {me.username} ({role})
            </span>
          </span>
          <button type="button" className="admin-signout" onClick={onSignOut}>
            <Icon name="logout" size={15} />
            Sign out
          </button>
        </header>

        <main className="admin-main">
          {tab === "dashboard" && (
            <Dashboard key={viewKey} client={client} onAuthError={onSignOut} />
          )}
          {tab === "insights" && (
            <Insights key={viewKey} client={client} role={role} onAuthError={onSignOut} />
          )}
          {tab === "funnel" && <Funnel key={viewKey} client={client} onAuthError={onSignOut} />}
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
          {tab === "model" && (
            <ModelProvider key={viewKey} client={client} role={role} onAuthError={onSignOut} />
          )}
          {tab === "usage" && <Usage key={viewKey} client={client} onAuthError={onSignOut} />}
        </main>
      </div>
    </div>
  );
}

export default function AdminApp() {
  // Credentials + identity live in memory; also mirrored to sessionStorage so a
  // browser refresh doesn't force re-login (cleared on sign-out / tab close).
  const [creds, setCreds] = useState<AdminCreds | null>(null);
  const [me, setMe] = useState<MeResponse | null>(null);
  // While we verify a persisted session on first load, show a boot state instead
  // of flashing the login screen.
  const [restoring, setRestoring] = useState(true);

  const client = useMemo(() => (creds ? createAdminClient(creds) : null), [creds]);

  useEffect(() => {
    const stored = loadStoredCreds();
    if (!stored) {
      setRestoring(false);
      return;
    }
    let active = true;
    createAdminClient(stored)
      .getMe()
      .then((identity) => {
        if (!active) return;
        setMe(identity);
        setCreds(stored);
      })
      .catch(() => {
        // Stale/invalid persisted creds (e.g. password rotated) — drop them.
        clearStoredCreds();
      })
      .finally(() => {
        if (active) setRestoring(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function authenticate(candidate: AdminCreds) {
    // Verify by calling /me; a 401 throws AdminAuthError (surfaced by Login as
    // "Invalid admin credentials.") and the response gives us the role so we
    // can gate admin-only actions.
    const probe = createAdminClient(candidate);
    const identity = await probe.getMe();
    setMe(identity);
    setCreds(candidate);
    storeCreds(candidate);
  }

  function signOut() {
    setCreds(null);
    setMe(null);
    clearStoredCreds();
  }

  if (restoring) {
    return <div className="admin-boot">Loading…</div>;
  }

  if (!creds || !client || !me) {
    return <Login onAuthenticate={authenticate} />;
  }

  return <Shell client={client} me={me} onSignOut={signOut} />;
}
