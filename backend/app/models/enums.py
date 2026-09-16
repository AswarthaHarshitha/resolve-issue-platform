import enum


class IssueStatus(str, enum.Enum):
    """Business lifecycle. Never conflated with AIAnalysisStatus (see DECISIONS.md D2)."""

    OPEN = "OPEN"
    TRIAGED = "TRIAGED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class AIAnalysisStatus(str, enum.Enum):
    """Independent AI-pipeline state. Never a substitute for IssueStatus."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class IssuePriority(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class StatusChangeTrigger(str, enum.Enum):
    """Why a status_history row exists, per DECISIONS.md D2/D8/D11."""

    SYSTEM_CREATE = "SYSTEM_CREATE"
    MANUAL = "MANUAL"
    AUTO_USER_REPLY = "AUTO_USER_REPLY"
    AI_ROUTING = "AI_ROUTING"
    ADMIN_OVERRIDE = "ADMIN_OVERRIDE"


class AIAnalysisResultStatus(str, enum.Enum):
    """Outcome of one classification attempt, recorded in
    ai_analysis_results. Distinct from AIAnalysisStatus, which tracks the
    issue's *current* AI pipeline state, not a specific attempt's outcome."""

    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
