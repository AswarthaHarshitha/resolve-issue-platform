import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { ProtectedRoute } from "./ProtectedRoute";

/**
 * Requires both an authenticated session (via ProtectedRoute) and the
 * ADMIN role. Like ProtectedRoute, this is a navigation convenience only -
 * every admin endpoint independently re-checks the role server-side
 * (DECISIONS.md D24, D41); a non-admin who bypasses this component still
 * gets a 403 from the API, not a data leak.
 */
export function AdminRoute({ children }: { children: ReactNode }) {
  const { user } = useAuth();

  return (
    <ProtectedRoute>
      {user?.role.name === "ADMIN" ? children : <Navigate to="/" replace />}
    </ProtectedRoute>
  );
}
