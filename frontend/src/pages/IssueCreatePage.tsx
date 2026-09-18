import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import { useAuth } from "../context/AuthContext";
import { ApiError } from "../services/api";
import { createIssue } from "../services/issuesApi";

export function IssueCreatePage() {
  const { token } = useAuth();
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!token) return;
    setError(null);
    setSubmitting(true);
    try {
      const issue = await createIssue(token, title, description);
      navigate(`/issues/${issue.id}`, { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AppShell title="New issue">
      <div className="max-w-xl rounded-lg border border-border bg-surface p-6">
        <p className="mb-4 text-sm text-text-secondary">
          Describe the problem. An AI classification step will suggest a category and priority shortly after
          submission, and a resolver will pick it up from there.
        </p>
        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <div>
            <label htmlFor="title" className="block text-sm font-medium text-text-primary">
              Title
            </label>
            <input
              id="title"
              type="text"
              required
              maxLength={200}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-text-primary focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>
          <div>
            <label htmlFor="description" className="block text-sm font-medium text-text-primary">
              Description
            </label>
            <textarea
              id="description"
              required
              rows={6}
              maxLength={5000}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-text-primary focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>

          {error && (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-surface transition hover:opacity-90 disabled:opacity-60"
          >
            {submitting ? "Submitting..." : "Submit issue"}
          </button>
        </form>
      </div>
    </AppShell>
  );
}
