import type { Team } from "./auth";

export type IssueStatus =
  | "OPEN"
  | "TRIAGED"
  | "ASSIGNED"
  | "IN_PROGRESS"
  | "WAITING_FOR_USER"
  | "RESOLVED"
  | "CLOSED";

export type AIAnalysisStatus = "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED";

export type IssuePriority = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface UserSummary {
  id: string;
  full_name: string;
  email: string;
}

export interface CategorySummary {
  id: string;
  name: string;
}

export interface SLAStatus {
  first_response_deadline_at: string;
  resolution_deadline_at: string;
  effective_elapsed_seconds: number;
  accumulated_pause_seconds: number;
  is_paused: boolean;
  first_response_met: boolean;
  resolution_met: boolean;
  first_response_at_risk: boolean;
  first_response_breached: boolean;
  resolution_at_risk: boolean;
  resolution_breached: boolean;
}

export interface Issue {
  id: string;
  title: string;
  description: string;
  status: IssueStatus;
  ai_analysis_status: AIAnalysisStatus;
  priority: IssuePriority | null;
  category: CategorySummary | null;
  sub_category: CategorySummary | null;
  owner: UserSummary;
  current_team: Team | null;
  current_resolver: UserSummary | null;
  sla: SLAStatus | null;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  closed_at: string | null;
}

export interface IssueListResponse {
  items: Issue[];
  total: number;
  page: number;
  page_size: number;
}

export interface Comment {
  id: string;
  author: UserSummary;
  body: string;
  created_at: string;
}

export interface StatusHistoryEntry {
  id: string;
  previous_status: IssueStatus | null;
  new_status: IssueStatus;
  trigger: "SYSTEM_CREATE" | "MANUAL" | "AUTO_USER_REPLY" | "AI_ROUTING" | "ADMIN_OVERRIDE";
  changed_by: UserSummary | null;
  note: string | null;
  created_at: string;
}
