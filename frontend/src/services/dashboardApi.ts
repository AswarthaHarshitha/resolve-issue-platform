import { apiRequest } from "./api";
import type { DashboardBreakdown, DashboardSummary } from "../types/dashboard";
import type { Issue } from "../types/issue";

export function getSummary(token: string): Promise<DashboardSummary> {
  return apiRequest<DashboardSummary>("/api/v1/dashboard/summary", {}, token);
}

export function getAtRiskIssues(token: string, limit = 10): Promise<Issue[]> {
  return apiRequest<Issue[]>(`/api/v1/dashboard/at-risk-issues?limit=${limit}`, {}, token);
}

export function getBreakdown(token: string): Promise<DashboardBreakdown> {
  return apiRequest<DashboardBreakdown>("/api/v1/dashboard/breakdown", {}, token);
}
