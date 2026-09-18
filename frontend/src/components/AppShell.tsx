import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

interface AppShellProps {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
}

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `block rounded-md px-3 py-2 text-sm font-medium transition ${
    isActive ? "bg-accent text-surface" : "text-text-primary hover:bg-background"
  }`;

const mobileNavLinkClass = ({ isActive }: { isActive: boolean }) =>
  `flex flex-1 flex-col items-center rounded-md px-2 py-1.5 text-xs font-medium transition ${
    isActive ? "text-accent" : "text-text-secondary"
  }`;

function NavLinks({ role, onLinkClass }: { role?: string; onLinkClass: (a: { isActive: boolean }) => string }) {
  return (
    <>
      <NavLink to="/" end className={onLinkClass}>
        Dashboard
      </NavLink>
      <NavLink to="/issues" className={onLinkClass}>
        Issues
      </NavLink>
      <NavLink to="/issues/new" className={onLinkClass}>
        New issue
      </NavLink>
      {role === "ADMIN" && (
        <NavLink to="/admin" className={onLinkClass}>
          Admin
        </NavLink>
      )}
    </>
  );
}

export function AppShell({ title, actions, children }: AppShellProps) {
  const { user, logout } = useAuth();
  const role = user?.role.name;

  return (
    <div className="flex min-h-screen flex-col bg-background sm:flex-row">
      <aside className="hidden w-56 shrink-0 border-r border-border bg-surface p-4 sm:block">
        <div className="mb-6 px-2">
          <p className="text-sm font-semibold text-text-primary">Resolve</p>
          <p className="text-xs text-text-secondary">Issue Resolution</p>
        </div>
        <nav className="space-y-1">
          <NavLinks role={role} onLinkClass={navLinkClass} />
        </nav>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-surface px-4 py-3 sm:px-6 sm:py-4">
          <div>
            <h1 className="text-lg font-semibold text-text-primary">{title}</h1>
            {user && (
              <p className="text-xs text-text-secondary">
                {user.full_name} · {user.role.name}
                {user.team ? ` · ${user.team.name}` : ""}
              </p>
            )}
          </div>
          <div className="flex items-center gap-3">
            {actions}
            <button
              onClick={logout}
              className="rounded-md border border-border px-3 py-1.5 text-sm text-text-primary transition hover:bg-background"
            >
              Log out
            </button>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto p-4 pb-20 sm:p-6 sm:pb-6">{children}</main>

        <nav className="fixed inset-x-0 bottom-0 flex items-stretch border-t border-border bg-surface px-2 py-1 sm:hidden">
          <NavLinks role={role} onLinkClass={mobileNavLinkClass} />
        </nav>
      </div>
    </div>
  );
}
