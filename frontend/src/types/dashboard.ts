export interface DashboardSummary {
  open_requests: number;
  high_priority: number;
  sla_at_risk: number;
  resolved_today: number;
}

export interface DashboardBreakdown {
  status_counts: Record<string, number>;
  priority_counts: Record<string, number>;
  ai_analysis_failures: number;
  team_workload: Record<string, number>;
}
