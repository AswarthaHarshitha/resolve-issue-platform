from typing import Dict

from pydantic import BaseModel


class DashboardSummaryPublic(BaseModel):
    open_requests: int
    high_priority: int
    sla_at_risk: int
    resolved_today: int


class DashboardBreakdownPublic(BaseModel):
    status_counts: Dict[str, int]
    priority_counts: Dict[str, int]
    ai_analysis_failures: int
    team_workload: Dict[str, int]
