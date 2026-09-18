import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AdminRoute } from "./components/AdminRoute";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { AuthProvider } from "./context/AuthContext";
import { ActivateAccountPage } from "./pages/ActivateAccountPage";
import { AdminPage } from "./pages/AdminPage";
import { DashboardPage } from "./pages/DashboardPage";
import { IssueCreatePage } from "./pages/IssueCreatePage";
import { IssueDetailPage } from "./pages/IssueDetailPage";
import { IssuesListPage } from "./pages/IssuesListPage";
import { LoginLandingPage } from "./pages/LoginLandingPage";
import { RegisterPage } from "./pages/RegisterPage";
import { RoleLoginPage } from "./pages/RoleLoginPage";

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginLandingPage />} />
          <Route
            path="/student-login"
            element={<RoleLoginPage context="student" title="Student Login" subtitle="Report and track issues" />}
          />
          <Route
            path="/resolver-login"
            element={
              <RoleLoginPage context="resolver" title="Resolver Login" subtitle="Resolve issues for your team" />
            }
          />
          <Route
            path="/admin-login"
            element={<RoleLoginPage context="admin" title="Admin Login" subtitle="Manage the platform" />}
          />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/activate" element={<ActivateAccountPage />} />
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <DashboardPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/issues"
            element={
              <ProtectedRoute>
                <IssuesListPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/issues/new"
            element={
              <ProtectedRoute>
                <IssueCreatePage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/issues/:issueId"
            element={
              <ProtectedRoute>
                <IssueDetailPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin"
            element={
              <AdminRoute>
                <AdminPage />
              </AdminRoute>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
