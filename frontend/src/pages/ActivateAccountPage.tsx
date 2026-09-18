import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { ApiError } from "../services/api";

/**
 * Reached from an admin-shared activation link (?token=...). The token is
 * the proof of authorization here - there is no login required to reach
 * this page, exactly like a password-reset link. The account does not
 * exist in the database until this form succeeds; the role/team it gets
 * were fixed by the admin at invite time and cannot be influenced from
 * here (DECISIONS.md D52).
 */
export function ActivateAccountPage() {
  const { activate } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") ?? "";

  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await activate(token, password, fullName);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  if (!token) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background px-4">
        <div className="w-full max-w-sm rounded-lg border border-border bg-surface p-8 text-center shadow-sm">
          <h1 className="text-lg font-semibold text-text-primary">Missing activation link</h1>
          <p className="mt-2 text-sm text-text-secondary">
            This page needs the activation link an admin sent you, not a bare visit.
          </p>
          <Link to="/login" className="mt-4 inline-block text-sm font-medium text-accent hover:underline">
            Go to sign in
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm rounded-lg border border-border bg-surface p-8 shadow-sm">
        <h1 className="text-xl font-semibold text-text-primary">Activate your account</h1>
        <p className="mt-1 text-sm text-text-secondary">Set your own password to finish setting up your account.</p>

        <form onSubmit={handleSubmit} className="mt-6 space-y-4" noValidate>
          <div>
            <label htmlFor="full_name" className="block text-sm font-medium text-text-primary">
              Full name
            </label>
            <input
              id="full_name"
              required
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
              className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-text-primary focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium text-text-primary">
              Choose a password
            </label>
            <input
              id="password"
              type="password"
              required
              autoComplete="new-password"
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
            {submitting ? "Activating..." : "Activate account"}
          </button>
        </form>
      </div>
    </div>
  );
}
