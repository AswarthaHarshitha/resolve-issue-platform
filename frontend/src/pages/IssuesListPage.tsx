import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import { PriorityBadge } from "../components/PriorityBadge";
import { StatusBadge } from "../components/StatusBadge";
import { useAuth } from "../context/AuthContext";
import { ALL_STATUSES, listIssues } from "../services/issuesApi";
import type { Issue, IssueStatus } from "../types/issue";

const PAGE_SIZE = 20;

export function IssuesListPage() {
  const { token } = useAuth();
  const [issues, setIssues] = useState<Issue[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<IssueStatus | "">("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    setLoading(true);
    listIssues(token, { page, pageSize: PAGE_SIZE, status: statusFilter || undefined })
      .then((result) => {
        setIssues(result.items);
        setTotal(result.total);
      })
      .catch(() => setError("Could not load issues."))
      .finally(() => setLoading(false));
  }, [token, page, statusFilter]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <AppShell
      title="Issues"
      actions={
        <Link
          to="/issues/new"
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-surface transition hover:opacity-90"
        >
          New issue
        </Link>
      }
    >
      <div className="mb-4 flex items-center gap-3">
        <label htmlFor="status-filter" className="text-sm text-text-secondary">
          Status
        </label>
        <select
          id="status-filter"
          value={statusFilter}
          onChange={(event) => {
            setPage(1);
            setStatusFilter(event.target.value as IssueStatus | "");
          }}
          className="rounded-md border border-border bg-surface px-2 py-1 text-sm text-text-primary"
        >
          <option value="">All</option>
          {ALL_STATUSES.map((status) => (
            <option key={status} value={status}>
              {status}
            </option>
          ))}
        </select>
      </div>

      {error && <p className="mb-4 text-sm text-danger">{error}</p>}

      <div className="overflow-x-auto rounded-lg border border-border bg-surface">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className="border-b border-border bg-background text-xs uppercase tracking-wide text-text-secondary">
            <tr>
              <th className="px-4 py-2">Title</th>
              <th className="px-4 py-2">Status</th>
              <th className="px-4 py-2">Priority</th>
              <th className="px-4 py-2">Team</th>
              <th className="px-4 py-2">AI</th>
              <th className="px-4 py-2">SLA</th>
              <th className="px-4 py-2">Created</th>
            </tr>
          </thead>
          <tbody>
            {!loading && issues.length === 0 && (
              <tr>
                <td className="px-4 py-6 text-center text-text-secondary" colSpan={7}>
                  No issues found.
                </td>
              </tr>
            )}
            {issues.map((issue) => {
              const slaBreached = issue.sla && (issue.sla.first_response_breached || issue.sla.resolution_breached);
              const slaAtRisk = issue.sla && (issue.sla.first_response_at_risk || issue.sla.resolution_at_risk);
              return (
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
                <td className="px-4 py-3 text-text-secondary">{issue.current_team?.name ?? "Unassigned"}</td>
                <td className="px-4 py-3 text-text-secondary">{issue.ai_analysis_status}</td>
                <td className="px-4 py-3">
                  {!issue.sla ? (
                    <span className="text-text-secondary">—</span>
                  ) : slaBreached ? (
                    <span className="text-danger">Breached</span>
                  ) : slaAtRisk ? (
                    <span className="text-warning">At risk</span>
                  ) : (
                    <span className="text-success">On track</span>
                  )}
                </td>
                <td className="px-4 py-3 text-text-secondary">{new Date(issue.created_at).toLocaleDateString()}</td>
              </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-4 flex items-center justify-between text-sm text-text-secondary">
        <span>
          Page {page} of {totalPages} ({total} total)
        </span>
        <div className="flex gap-2">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="rounded-md border border-border px-3 py-1 disabled:opacity-40"
          >
            Previous
          </button>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="rounded-md border border-border px-3 py-1 disabled:opacity-40"
          >
            Next
          </button>
        </div>
      </div>
    </AppShell>
  );
}
