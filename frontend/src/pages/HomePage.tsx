import { useAuth } from "../context/AuthContext";

/**
 * Minimal authenticated landing page. Deliberately not a dashboard - Phase 3
 * only needs to prove register -> login -> authenticated session -> /me ->
 * logout works end to end. Role-specific dashboards land in a later phase.
 */
export function HomePage() {
  const { user, logout } = useAuth();

  if (!user) {
    return null;
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="flex items-center justify-between border-b border-border bg-surface px-6 py-4">
        <div>
          <p className="text-sm font-semibold text-text-primary">Resolve</p>
          <p className="text-xs text-text-secondary">Intelligent Issue Resolution Platform</p>
        </div>
        <button
          onClick={logout}
          className="rounded-md border border-border px-3 py-1.5 text-sm text-text-primary transition hover:bg-background"
        >
          Log out
        </button>
      </header>

      <main className="mx-auto max-w-2xl px-6 py-10">
        <div className="rounded-lg border border-border bg-surface p-6">
          <h1 className="text-lg font-semibold text-text-primary">Signed in</h1>

          <dl className="mt-4 space-y-2 text-sm">
            <div className="flex justify-between border-b border-border py-2">
              <dt className="text-text-secondary">Name</dt>
              <dd className="text-text-primary">{user.full_name}</dd>
            </div>
            <div className="flex justify-between border-b border-border py-2">
              <dt className="text-text-secondary">Email</dt>
              <dd className="text-text-primary">{user.email}</dd>
            </div>
            <div className="flex justify-between border-b border-border py-2">
              <dt className="text-text-secondary">Role</dt>
              <dd className="text-text-primary">{user.role.name}</dd>
            </div>
            {user.team && (
              <div className="flex justify-between py-2">
                <dt className="text-text-secondary">Team</dt>
                <dd className="text-text-primary">{user.team.name}</dd>
              </div>
            )}
          </dl>

          <p className="mt-6 text-sm text-text-secondary">
            Issue creation, dashboards, and the rest of Resolve are built in later phases. This
            page exists to demonstrate the authentication flow.
          </p>
        </div>
      </main>
    </div>
  );
}
