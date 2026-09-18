import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import type { LoginContext } from "../services/authApi";
import { ApiError } from "../services/api";

interface RoleLoginPageProps {
  context: LoginContext;
  title: string;
  subtitle: string;
}

/**
 * The one shared login form behind all three entry points
 * (/student-login, /resolver-login, /admin-login) - same auth service, same
 * validation, same error handling. `context` is passed to the backend as a
 * UX hint only ("which door did this come through"); the backend is the
 * only thing that ever decides whether the account's real database role
 * actually belongs there (see DECISIONS.md D50). A mismatch fails with the
 * same generic message as a wrong password, so this page can't be used to
 * probe which role an account actually has.
 */
export function RoleLoginPage({ context, title, subtitle }: RoleLoginPageProps) {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password, context);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm rounded-lg border border-border bg-surface p-8 shadow-sm">
        <Link to="/login" className="text-xs font-medium text-accent hover:underline">
          ← Choose a different sign-in
        </Link>
        <h1 className="mt-3 text-xl font-semibold text-text-primary">{title}</h1>
        <p className="mt-1 text-sm text-text-secondary">{subtitle}</p>

        <form onSubmit={handleSubmit} className="mt-6 space-y-4" noValidate>
          <div>
            <label htmlFor="email" className="block text-sm font-medium text-text-primary">
              Email
            </label>
            <input
              id="email"
              name="email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-text-primary focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium text-text-primary">
              Password
            </label>
            <input
              id="password"
              name="password"
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-text-primary focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>

          {error && (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-md bg-accent px-4 py-2 text-sm font-medium text-surface transition hover:opacity-90 disabled:opacity-60"
          >
            {submitting ? "Signing in..." : title}
          </button>
        </form>

        {context === "student" && (
          <p className="mt-6 text-center text-sm text-text-secondary">
            Don&apos;t have an account?{" "}
            <Link to="/register" className="font-medium text-accent hover:underline">
              Register
            </Link>
          </p>
        )}
      </div>
    </div>
  );
}
