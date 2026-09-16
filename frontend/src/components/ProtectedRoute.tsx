import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

/**
 * Redirects to /login when there's no authenticated session. This is a
 * navigation convenience only, not a security boundary - the backend
 * enforces every actual permission check independently (DECISIONS.md D24).
 * A user could disable JavaScript and hit a protected API route directly;
 * the API rejects them regardless of anything this component does.
 */
export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background text-sm text-text-secondary">
        Loading...
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
}
