import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useParams } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import { PriorityBadge } from "../components/PriorityBadge";
import { StatusBadge } from "../components/StatusBadge";
import { useAuth } from "../context/AuthContext";
import { ApiError } from "../services/api";
import {
  addComment,
  confirmResolution,
  getAIAnalysis,
  getHistory,
  getIssue,
  listComments,
  reanalyzeIssue,
  rejectResolution,
  updateAssignment,
  updateIssueStatus,
} from "../services/issuesApi";
import type { AIAnalysisResult } from "../types/aiAnalysis";
import type { Comment, Issue, IssueStatus, StatusHistoryEntry } from "../types/issue";

const NEXT_STATUSES: Record<IssueStatus, IssueStatus[]> = {
  OPEN: [],
  TRIAGED: ["ASSIGNED"],
  ASSIGNED: ["IN_PROGRESS"],
  IN_PROGRESS: ["WAITING_FOR_USER", "RESOLVED"],
  WAITING_FOR_USER: ["IN_PROGRESS"],
  RESOLVED: [],
  CLOSED: [],
};

function formatSeconds(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

export function IssueDetailPage() {
  const { issueId } = useParams<{ issueId: string }>();
  const { user, token } = useAuth();
  const [issue, setIssue] = useState<Issue | null>(null);
  const [history, setHistory] = useState<StatusHistoryEntry[]>([]);
  const [comments, setComments] = useState<Comment[]>([]);
  const [aiAnalysis, setAiAnalysis] = useState<AIAnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [newComment, setNewComment] = useState("");
  const [submittingComment, setSubmittingComment] = useState(false);

  const load = useCallback(() => {
    if (!token || !issueId) return;
    Promise.all([getIssue(token, issueId), getHistory(token, issueId), listComments(token, issueId), getAIAnalysis(token, issueId)])
      .then(([issueResult, historyResult, commentsResult, aiResult]) => {
        setIssue(issueResult);
        setHistory(historyResult);
        setComments(commentsResult);
        setAiAnalysis(aiResult);
      })
      .catch(() => setError("Could not load this issue."));
  }, [token, issueId]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleTransition(target: IssueStatus) {
    if (!token || !issueId) return;
    setActionError(null);
    try {
      await updateIssueStatus(token, issueId, target);
      load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not update status.");
    }
  }

  async function handleAssignToMe() {
    if (!token || !issueId) return;
    setActionError(null);
    try {
      await updateAssignment(token, issueId, {});
      load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not assign this issue.");
    }
  }

  async function handleReanalyze() {
    if (!token || !issueId) return;
    setActionError(null);
    try {
      await reanalyzeIssue(token, issueId);
      load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not trigger reanalysis.");
    }
  }

  async function handleConfirm() {
    if (!token || !issueId) return;
    setActionError(null);
    try {
      await confirmResolution(token, issueId);
      load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not confirm resolution.");
    }
  }

  async function handleReject() {
    if (!token || !issueId) return;
    setActionError(null);
    try {
      await rejectResolution(token, issueId);
      load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not reject resolution.");
    }
  }

  async function handleAddComment(event: FormEvent) {
    event.preventDefault();
    if (!token || !issueId || !newComment.trim()) return;
    setSubmittingComment(true);
    setActionError(null);
    try {
      await addComment(token, issueId, newComment.trim());
      setNewComment("");
      load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not add comment.");
    } finally {
      setSubmittingComment(false);
    }
  }

  if (error) {
    return (
      <AppShell title="Issue">
        <p className="text-sm text-danger">{error}</p>
      </AppShell>
    );
  }

  if (!issue) {
    return (
      <AppShell title="Issue">
        <p className="text-sm text-text-secondary">Loading...</p>
      </AppShell>
    );
  }

  const isStaff = user?.role.name === "RESOLVER" || user?.role.name === "ADMIN";
  const isOwner = user?.id === issue.owner.id;
  const nextStatuses = NEXT_STATUSES[issue.status];

  return (
    <AppShell title={issue.title}>
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <section className="rounded-lg border border-border bg-surface p-5">
            <div className="flex flex-wrap items-center gap-3">
              <StatusBadge status={issue.status} />
              <PriorityBadge priority={issue.priority} />
              {issue.category && (
                <span className="text-xs text-text-secondary">
                  {issue.category.name}
                  {issue.sub_category ? ` / ${issue.sub_category.name}` : ""}
                </span>
              )}
            </div>
            <p className="mt-4 whitespace-pre-wrap text-sm text-text-primary">{issue.description}</p>
            <dl className="mt-4 grid grid-cols-2 gap-2 text-xs text-text-secondary sm:grid-cols-4">
              <div>
                <dt className="uppercase tracking-wide">Owner</dt>
                <dd className="text-text-primary">{issue.owner.full_name}</dd>
              </div>
              <div>
                <dt className="uppercase tracking-wide">Team</dt>
                <dd className="text-text-primary">{issue.current_team?.name ?? "Unassigned"}</dd>
              </div>
              <div>
                <dt className="uppercase tracking-wide">Resolver</dt>
                <dd className="text-text-primary">{issue.current_resolver?.full_name ?? "Unassigned"}</dd>
              </div>
              <div>
                <dt className="uppercase tracking-wide">Created</dt>
                <dd className="text-text-primary">{new Date(issue.created_at).toLocaleString()}</dd>
              </div>
            </dl>
          </section>

          <section className="rounded-lg border border-border bg-surface p-5">
            <h2 className="text-sm font-semibold text-text-primary">AI analysis</h2>
            <p className="mt-1 text-xs text-text-secondary">
              Status: {issue.ai_analysis_status}
              {isStaff && (
                <button onClick={handleReanalyze} className="ml-3 font-medium text-accent hover:underline">
                  Re-run analysis
                </button>
              )}
            </p>
            {aiAnalysis ? (
              aiAnalysis.status === "FAILED" ? (
                <p className="mt-3 text-sm text-danger">{aiAnalysis.error_message ?? "Analysis failed."}</p>
              ) : (
                <div className="mt-3 space-y-2 text-sm text-text-primary">
                  <p>
                    <span className="text-text-secondary">Summary: </span>
                    {aiAnalysis.summary}
                  </p>
                  <p>
                    <span className="text-text-secondary">Reasoning: </span>
                    {aiAnalysis.reasoning}
                  </p>
                </div>
              )
            ) : (
              <p className="mt-3 text-sm text-text-secondary">No analysis yet.</p>
            )}
          </section>

          {issue.sla && (
            <section className="rounded-lg border border-border bg-surface p-5">
              <h2 className="text-sm font-semibold text-text-primary">SLA</h2>
              <dl className="mt-3 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
                <div>
                  <dt className="uppercase tracking-wide text-text-secondary">First response</dt>
                  <dd className={issue.sla.first_response_breached ? "text-danger" : issue.sla.first_response_at_risk ? "text-warning" : "text-text-primary"}>
                    {issue.sla.first_response_met
                      ? "Met"
                      : issue.sla.first_response_breached
                        ? "Breached"
                        : issue.sla.first_response_at_risk
                          ? "At risk"
                          : "On track"}
                  </dd>
                </div>
                <div>
                  <dt className="uppercase tracking-wide text-text-secondary">Resolution</dt>
                  <dd className={issue.sla.resolution_breached ? "text-danger" : issue.sla.resolution_at_risk ? "text-warning" : "text-text-primary"}>
                    {issue.sla.resolution_met
                      ? "Met"
                      : issue.sla.resolution_breached
                        ? "Breached"
                        : issue.sla.resolution_at_risk
                          ? "At risk"
                          : "On track"}
                  </dd>
                </div>
                <div>
                  <dt className="uppercase tracking-wide text-text-secondary">Elapsed</dt>
                  <dd className="text-text-primary">{formatSeconds(issue.sla.effective_elapsed_seconds)}</dd>
                </div>
                <div>
                  <dt className="uppercase tracking-wide text-text-secondary">Paused</dt>
                  <dd className="text-text-primary">{issue.sla.is_paused ? "Yes" : "No"}</dd>
                </div>
              </dl>
            </section>
          )}

          <section className="rounded-lg border border-border bg-surface p-5">
            <h2 className="text-sm font-semibold text-text-primary">Activity</h2>
            <ol className="mt-3 space-y-3 border-l border-border pl-4 text-sm">
              {history.map((entry) => (
                <li key={entry.id}>
                  <p className="text-text-primary">
                    {entry.previous_status ? `${entry.previous_status} → ${entry.new_status}` : `Created (${entry.new_status})`}
                  </p>
                  <p className="text-xs text-text-secondary">
                    {new Date(entry.created_at).toLocaleString()}
                    {entry.changed_by ? ` · ${entry.changed_by.full_name}` : " · system"}
                  </p>
                </li>
              ))}
            </ol>
          </section>

          <section className="rounded-lg border border-border bg-surface p-5">
            <h2 className="text-sm font-semibold text-text-primary">Comments</h2>
            <div className="mt-3 space-y-3">
              {comments.length === 0 && <p className="text-sm text-text-secondary">No comments yet.</p>}
              {comments.map((comment) => (
                <div key={comment.id} className="rounded-md border border-border bg-background p-3">
                  <p className="text-xs text-text-secondary">
                    {comment.author.full_name} · {new Date(comment.created_at).toLocaleString()}
                  </p>
                  <p className="mt-1 text-sm text-text-primary">{comment.body}</p>
                </div>
              ))}
            </div>
            <form onSubmit={handleAddComment} className="mt-4 space-y-2">
              <textarea
                value={newComment}
                onChange={(event) => setNewComment(event.target.value)}
                rows={3}
                placeholder="Add a comment..."
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-text-primary focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
              />
              <button
                type="submit"
                disabled={submittingComment || !newComment.trim()}
                className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-surface transition hover:opacity-90 disabled:opacity-60"
              >
                {submittingComment ? "Posting..." : "Post comment"}
              </button>
            </form>
          </section>
        </div>

        <div className="space-y-4">
          {actionError && <p className="text-sm text-danger">{actionError}</p>}

          {isStaff && (nextStatuses.length > 0 || !issue.current_resolver) && (
            <section className="rounded-lg border border-border bg-surface p-4">
              <h2 className="text-sm font-semibold text-text-primary">Resolver actions</h2>
              <div className="mt-3 space-y-2">
                {!issue.current_resolver && (
                  <button
                    onClick={handleAssignToMe}
                    className="w-full rounded-md border border-border px-3 py-1.5 text-sm text-text-primary hover:bg-background"
                  >
                    Assign to me
                  </button>
                )}
                {nextStatuses.map((next) => (
                  <button
                    key={next}
                    onClick={() => handleTransition(next)}
                    className="w-full rounded-md border border-border px-3 py-1.5 text-sm text-text-primary hover:bg-background"
                  >
                    Move to {next.replace(/_/g, " ").toLowerCase()}
                  </button>
                ))}
              </div>
            </section>
          )}

          {isOwner && issue.status === "RESOLVED" && (
            <section className="rounded-lg border border-border bg-surface p-4">
              <h2 className="text-sm font-semibold text-text-primary">Confirm resolution</h2>
              <p className="mt-1 text-xs text-text-secondary">
                A resolver marked this issue resolved. Confirm if the problem is actually fixed.
              </p>
              <div className="mt-3 flex gap-2">
                <button
                  onClick={handleConfirm}
                  className="flex-1 rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-surface hover:opacity-90"
                >
                  Confirm
                </button>
                <button
                  onClick={handleReject}
                  className="flex-1 rounded-md border border-border px-3 py-1.5 text-sm text-text-primary hover:bg-background"
                >
                  Reject
                </button>
              </div>
            </section>
          )}
        </div>
      </div>
    </AppShell>
  );
}
