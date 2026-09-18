import type { IssueStatus } from "../types/issue";

// Color communicates state, per the design system: neutral for
// administrative states, muted accent colors only where they carry real
// meaning (amber = active work, gray = blocked-on-someone-else, olive =
// done). No decorative color.
const STYLES: Record<IssueStatus, string> = {
  OPEN: "bg-background text-text-secondary border-border",
  TRIAGED: "bg-background text-accent border-accent/40",
  ASSIGNED: "bg-background text-text-secondary border-border",
  IN_PROGRESS: "bg-background text-warning border-warning/40",
  WAITING_FOR_USER: "bg-background text-text-secondary border-border",
  RESOLVED: "bg-background text-success border-success/40",
  CLOSED: "bg-background text-text-secondary border-border",
};

const LABELS: Record<IssueStatus, string> = {
  OPEN: "Open",
  TRIAGED: "Triaged",
  ASSIGNED: "Assigned",
  IN_PROGRESS: "In progress",
  WAITING_FOR_USER: "Waiting for user",
  RESOLVED: "Resolved",
  CLOSED: "Closed",
};

export function StatusBadge({ status }: { status: IssueStatus }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${STYLES[status]}`}
    >
      {LABELS[status]}
    </span>
  );
}
