import { apiRequest } from "./api";
import type { AIAnalysisResult } from "../types/aiAnalysis";
import type { Comment, Issue, IssueListResponse, IssuePriority, IssueStatus, StatusHistoryEntry } from "../types/issue";

export function createIssue(token: string, title: string, description: string): Promise<Issue> {
  return apiRequest<Issue>("/api/v1/issues", { method: "POST", body: JSON.stringify({ title, description }) }, token);
}

export function listIssues(
  token: string,
  params: { page?: number; pageSize?: number; status?: IssueStatus } = {},
): Promise<IssueListResponse> {
  const query = new URLSearchParams();
  if (params.page) query.set("page", String(params.page));
  if (params.pageSize) query.set("page_size", String(params.pageSize));
  if (params.status) query.set("status", params.status);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiRequest<IssueListResponse>(`/api/v1/issues${suffix}`, {}, token);
}

export function getIssue(token: string, issueId: string): Promise<Issue> {
  return apiRequest<Issue>(`/api/v1/issues/${issueId}`, {}, token);
}

export function updateIssueStatus(
  token: string,
  issueId: string,
  targetStatus: IssueStatus,
  note?: string,
): Promise<Issue> {
  return apiRequest<Issue>(
    `/api/v1/issues/${issueId}/status`,
    { method: "PATCH", body: JSON.stringify({ status: targetStatus, note: note ?? null }) },
    token,
  );
}

export function reanalyzeIssue(token: string, issueId: string): Promise<Issue> {
  return apiRequest<Issue>(`/api/v1/issues/${issueId}/reanalyze`, { method: "POST" }, token);
}

export function listComments(token: string, issueId: string): Promise<Comment[]> {
  return apiRequest<Comment[]>(`/api/v1/issues/${issueId}/comments`, {}, token);
}

export function addComment(token: string, issueId: string, body: string): Promise<Comment> {
  return apiRequest<Comment>(
    `/api/v1/issues/${issueId}/comments`,
    { method: "POST", body: JSON.stringify({ body }) },
    token,
  );
}

export function getHistory(token: string, issueId: string): Promise<StatusHistoryEntry[]> {
  return apiRequest<StatusHistoryEntry[]>(`/api/v1/issues/${issueId}/history`, {}, token);
}

export function getAIAnalysis(token: string, issueId: string): Promise<AIAnalysisResult | null> {
  return apiRequest<AIAnalysisResult | null>(`/api/v1/issues/${issueId}/ai-analysis`, {}, token);
}

export function updateAssignment(
  token: string,
  issueId: string,
  params: { teamId?: string; resolverId?: string; reason?: string },
): Promise<Issue> {
  return apiRequest<Issue>(
    `/api/v1/issues/${issueId}/assignment`,
    {
      method: "PATCH",
      body: JSON.stringify({
        team_id: params.teamId ?? null,
        resolver_id: params.resolverId ?? null,
        reason: params.reason ?? null,
      }),
    },
    token,
  );
}

export function confirmResolution(token: string, issueId: string): Promise<Issue> {
  return apiRequest<Issue>(`/api/v1/issues/${issueId}/resolution/confirm`, { method: "POST" }, token);
}

export function rejectResolution(token: string, issueId: string, note?: string): Promise<Issue> {
  return apiRequest<Issue>(
    `/api/v1/issues/${issueId}/resolution/reject`,
    { method: "POST", body: JSON.stringify({ status: "IN_PROGRESS", note: note ?? null }) },
    token,
  );
}

export const ALL_PRIORITIES: IssuePriority[] = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];
export const ALL_STATUSES: IssueStatus[] = [
  "OPEN",
  "TRIAGED",
  "ASSIGNED",
  "IN_PROGRESS",
  "WAITING_FOR_USER",
  "RESOLVED",
  "CLOSED",
];
