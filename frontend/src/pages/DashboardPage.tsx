import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import { PriorityBadge } from "../components/PriorityBadge";
import { StatusBadge } from "../components/StatusBadge";
import { useAuth } from "../context/AuthContext";
import { getAtRiskIssues, getBreakdown, getSummary } from "../services/dashboardApi";
import { listIssues } from "../services/issuesApi";
import type { DashboardBreakdown, DashboardSummary } from "../types/dashboard";
import type { Issue } from "../types/issue";

function MetricTile({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-text-secondary">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-text-primary">{value}</p>
    </div>
  );
}

function IssueTable({ issues, empty }: { issues: Issue[]; empty: string }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface">
      <table className="w-full min-w-[560px] text-left text-sm">
        <thead className="border-b border-border bg-background text-xs uppercase tracking-wide text-text-secondary">
          <tr>
            <th className="px-4 py-2">Title</th>
            <th className="px-4 py-2">Status</th>
            <th className="px-4 py-2">Priority</th>
            <th className="px-4 py-2">AI</th>
            <th className="px-4 py-2">Created</th>
          </tr>
        </thead>
        <tbody>
          {issues.length === 0 && (
            <tr>
              <td className="px-4 py-6 text-center text-text-secondary" colSpan={5}>
                {empty}
              </td>
            </tr>
          )}
          {issues.map((issue) => (
            <tr key={issue.id} className="border-b border-border last:border-0 hover:bg-background">
              <td className="px-4 py-3">
                <Link to={`/issues/${issue.id}`} className="font-medium text-text-primary hover:text-accent">
                  {issue.title}
                </Link>
              </td>
              <td className="px-4 py-3">
                <StatusBadge status={issue.status} />
              </td>
              <td className="px-4 py-3">
                <PriorityBadge priority={issue.priority} />
              </td>
              <td className="px-4 py-3 text-text-secondary">{issue.ai_analysis_status}</td>
              <td className="px-4 py-3 text-text-secondary">{new Date(issue.created_at).toLocaleDateString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CountList({ counts }: { counts: Record<string, number> }) {
  const entries = Object.entries(counts).filter(([, count]) => count > 0);
  if (entries.length === 0) {
    return <p className="text-sm text-text-secondary">No data yet.</p>;
  }
  return (
    <ul className="space-y-1 text-sm">
      {entries.map(([label, count]) => (
        <li key={label} className="flex justify-between border-b border-border py-1 last:border-0">
          <span className="text-text-secondary">{label.replace(/_/g, " ")}</span>
          <span className="font-medium text-text-primary">{count}</span>
        </li>
      ))}
    </ul>
  );
}

export function DashboardPage() {
  const { user, token } = useAuth();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [recentIssues, setRecentIssues] = useState<Issue[]>([]);
  const [atRiskIssues, setAtRiskIssues] = useState<Issue[]>([]);
  const [breakdown, setBreakdown] = useState<DashboardBreakdown | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const isStaff = user?.role.name === "RESOLVER" || user?.role.name === "ADMIN";

  useEffect(() => {
    if (!token) return;
    setLoading(true);
    Promise.all([
      getSummary(token),
      listIssues(token, { page: 1, pageSize: 10 }),
      getAtRiskIssues(token),
      getBreakdown(token),
    ])
      .then(([summaryResult, issuesResult, atRiskResult, breakdownResult]) => {
        setSummary(summaryResult);
        setRecentIssues(issuesResult.items);
        setAtRiskIssues(atRiskResult);
        setBreakdown(breakdownResult);
      })
      .catch(() => setError("Could not load dashboard data."))
      .finally(() => setLoading(false));
  }, [token]);

  return (
    <AppShell title="Dashboard">
      {error && <p className="mb-4 text-sm text-danger">{error}</p>}
      {loading && !summary && <p className="mb-4 text-sm text-text-secondary">Loading dashboard...</p>}

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <MetricTile label="Open requests" value={summary?.open_requests ?? 0} />
        <MetricTile label="High priority" value={summary?.high_priority ?? 0} />
        <MetricTile label="SLA at risk" value={summary?.sla_at_risk ?? 0} />
        <MetricTile label="Resolved today" value={summary?.resolved_today ?? 0} />
      </div>

      {isStaff && atRiskIssues.length > 0 && (
        <div className="mt-8">
          <h2 className="mb-3 text-sm font-semibold text-text-primary">SLA at risk</h2>
          <IssueTable issues={atRiskIssues} empty="Nothing at risk right now." />
        </div>
      )}

      <div className="mt-8">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-text-primary">Recent issues</h2>
          <Link to="/issues" className="text-sm font-medium text-accent hover:underline">
            View all
          </Link>
        </div>
        <IssueTable issues={recentIssues} empty="No issues yet." />
      </div>

      {isStaff && breakdown && (
        <div className="mt-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          <div className="rounded-lg border border-border bg-surface p-4">
            <h2 className="mb-2 text-sm font-semibold text-text-primary">Status distribution</h2>
            <CountList counts={breakdown.status_counts} />
          </div>
          <div className="rounded-lg border border-border bg-surface p-4">
            <h2 className="mb-2 text-sm font-semibold text-text-primary">Priority distribution</h2>
            <CountList counts={breakdown.priority_counts} />
          </div>
          {user?.role.name === "ADMIN" && (
            <div className="rounded-lg border border-border bg-surface p-4">
              <h2 className="mb-2 text-sm font-semibold text-text-primary">Team workload</h2>
              <CountList counts={breakdown.team_workload} />
              <p className="mt-3 text-xs text-text-secondary">AI analysis failures: {breakdown.ai_analysis_failures}</p>
            </div>
          )}
        </div>
      )}
    </AppShell>
  );
}
