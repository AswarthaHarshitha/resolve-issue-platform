import type { IssuePriority } from "../types/issue";

const STYLES: Record<IssuePriority, string> = {
  LOW: "text-text-secondary",
  MEDIUM: "text-text-primary",
  HIGH: "text-warning",
  CRITICAL: "text-danger",
};

export function PriorityBadge({ priority }: { priority: IssuePriority | null }) {
  if (!priority) {
    return <span className="text-xs text-text-secondary">Not set</span>;
  }
  return <span className={`text-xs font-semibold uppercase tracking-wide ${STYLES[priority]}`}>{priority}</span>;
}
