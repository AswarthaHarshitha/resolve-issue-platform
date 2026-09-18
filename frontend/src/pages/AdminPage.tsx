import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { AppShell } from "../components/AppShell";
import { useAuth } from "../context/AuthContext";
import { ApiError } from "../services/api";
import * as adminApi from "../services/adminApi";
import { ALL_PRIORITIES } from "../services/issuesApi";
import type { AdminCategory, AdminInvite, AdminRoutingRule, AdminSLARule, AdminTeam, AdminUser, CreatedInvite } from "../types/admin";
import type { IssuePriority } from "../types/issue";

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-border bg-surface p-5">
      <h2 className="text-sm font-semibold text-text-primary">{title}</h2>
      <div className="mt-3">{children}</div>
    </section>
  );
}

export function AdminPage() {
  const { token } = useAuth();
  const [teams, setTeams] = useState<AdminTeam[]>([]);
  const [categories, setCategories] = useState<AdminCategory[]>([]);
  const [routingRules, setRoutingRules] = useState<AdminRoutingRule[]>([]);
  const [slaRules, setSlaRules] = useState<AdminSLARule[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [pendingInvites, setPendingInvites] = useState<AdminInvite[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [newTeamName, setNewTeamName] = useState("");
  const [newCategoryName, setNewCategoryName] = useState("");
  const [subCategoryDrafts, setSubCategoryDrafts] = useState<Record<string, string>>({});
  const [routingCategoryId, setRoutingCategoryId] = useState("");
  const [routingTeamId, setRoutingTeamId] = useState("");
  const [slaCategoryId, setSlaCategoryId] = useState("");
  const [slaPriority, setSlaPriority] = useState<IssuePriority>("MEDIUM");
  const [slaFirstResponse, setSlaFirstResponse] = useState(60);
  const [slaResolution, setSlaResolution] = useState(1440);

  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"RESOLVER" | "ADMIN">("RESOLVER");
  const [inviteTeamId, setInviteTeamId] = useState("");
  const [lastCreatedInvite, setLastCreatedInvite] = useState<CreatedInvite | null>(null);

  function load() {
    if (!token) return;
    Promise.all([
      adminApi.listTeams(token),
      adminApi.listCategories(token),
      adminApi.listRoutingRules(token),
      adminApi.listSLARules(token),
      adminApi.listUsers(token),
      adminApi.listPendingInvites(token),
    ])
      .then(([teamsResult, categoriesResult, routingResult, slaResult, usersResult, invitesResult]) => {
        setTeams(teamsResult);
        setCategories(categoriesResult);
        setRoutingRules(routingResult);
        setSlaRules(slaResult);
        setUsers(usersResult);
        setPendingInvites(invitesResult);
      })
      .catch(() => setError("Could not load admin data."));
  }

  useEffect(load, [token]);

  async function handleCreateTeam(event: FormEvent) {
    event.preventDefault();
    if (!token || !newTeamName.trim()) return;
    try {
      await adminApi.createTeam(token, newTeamName.trim());
      setNewTeamName("");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create team.");
    }
  }

  async function handleCreateCategory(event: FormEvent) {
    event.preventDefault();
    if (!token || !newCategoryName.trim()) return;
    try {
      await adminApi.createCategory(token, newCategoryName.trim());
      setNewCategoryName("");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create category.");
    }
  }

  async function handleCreateSubCategory(categoryId: string) {
    const name = subCategoryDrafts[categoryId]?.trim();
    if (!token || !name) return;
    try {
      await adminApi.createSubCategory(token, categoryId, name);
      setSubCategoryDrafts((prev) => ({ ...prev, [categoryId]: "" }));
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create sub-category.");
    }
  }

  async function handleCreateRoutingRule(event: FormEvent) {
    event.preventDefault();
    if (!token || !routingCategoryId || !routingTeamId) return;
    try {
      await adminApi.createRoutingRule(token, { categoryId: routingCategoryId, teamId: routingTeamId });
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create routing rule.");
    }
  }

  async function handleCreateInvite(event: FormEvent) {
    event.preventDefault();
    if (!token || !inviteEmail.trim()) return;
    if (inviteRole === "RESOLVER" && !inviteTeamId) {
      setError("A resolver invite needs a team.");
      return;
    }
    try {
      const created = await adminApi.createInvite(token, {
        email: inviteEmail.trim(),
        role: inviteRole,
        teamId: inviteRole === "RESOLVER" ? inviteTeamId : undefined,
      });
      setLastCreatedInvite(created);
      setInviteEmail("");
      setInviteTeamId("");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create invite.");
    }
  }

  async function handleCreateSlaRule(event: FormEvent) {
    event.preventDefault();
    if (!token || !slaCategoryId) return;
    try {
      await adminApi.createSLARule(token, {
        categoryId: slaCategoryId,
        priority: slaPriority,
        firstResponseMinutes: slaFirstResponse,
        resolutionMinutes: slaResolution,
      });
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create SLA rule.");
    }
  }

  async function handlePromote(userId: string, teamId: string) {
    if (!token || !teamId) return;
    try {
      await adminApi.updateUser(token, userId, { role: "RESOLVER", teamId });
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update user.");
    }
  }

  async function handleToggleUserActive(user: AdminUser) {
    if (!token) return;
    try {
      await adminApi.updateUser(token, user.id, { isActive: !user.is_active });
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update user.");
    }
  }

  return (
    <AppShell title="Admin">
      {error && <p className="mb-4 text-sm text-danger">{error}</p>}

      <div className="grid gap-6 lg:grid-cols-2">
        <SectionCard title="Teams">
          <ul className="space-y-1 text-sm">
            {teams.map((team) => (
              <li key={team.id} className="flex items-center justify-between border-b border-border py-1 last:border-0">
                <span className={team.is_active ? "text-text-primary" : "text-text-secondary line-through"}>
                  {team.name}
                </span>
              </li>
            ))}
          </ul>
          <form onSubmit={handleCreateTeam} className="mt-3 flex gap-2">
            <input
              value={newTeamName}
              onChange={(event) => setNewTeamName(event.target.value)}
              placeholder="New team name"
              className="flex-1 rounded-md border border-border bg-background px-2 py-1 text-sm text-text-primary"
            />
            <button type="submit" className="rounded-md bg-accent px-3 py-1 text-sm font-medium text-surface hover:opacity-90">
              Add
            </button>
          </form>
        </SectionCard>

        <SectionCard title="Categories & sub-categories">
          <ul className="space-y-2 text-sm">
            {categories.map((category) => (
              <li key={category.id}>
                <p className="font-medium text-text-primary">{category.name}</p>
                <p className="text-xs text-text-secondary">
                  {category.sub_categories.map((s) => s.name).join(", ") || "No sub-categories yet"}
                </p>
                <div className="mt-1 flex gap-2">
                  <input
                    value={subCategoryDrafts[category.id] ?? ""}
                    onChange={(event) =>
                      setSubCategoryDrafts((prev) => ({ ...prev, [category.id]: event.target.value }))
                    }
                    placeholder="New sub-category"
                    className="flex-1 rounded-md border border-border bg-background px-2 py-1 text-xs text-text-primary"
                  />
                  <button
                    onClick={() => handleCreateSubCategory(category.id)}
                    className="rounded-md border border-border px-2 py-1 text-xs text-text-primary hover:bg-background"
                  >
                    Add
                  </button>
                </div>
              </li>
            ))}
          </ul>
          <form onSubmit={handleCreateCategory} className="mt-3 flex gap-2">
            <input
              value={newCategoryName}
              onChange={(event) => setNewCategoryName(event.target.value)}
              placeholder="New category name"
              className="flex-1 rounded-md border border-border bg-background px-2 py-1 text-sm text-text-primary"
            />
            <button type="submit" className="rounded-md bg-accent px-3 py-1 text-sm font-medium text-surface hover:opacity-90">
              Add
            </button>
          </form>
        </SectionCard>

        <SectionCard title="Routing rules">
          <ul className="space-y-1 text-sm">
            {routingRules.map((rule) => (
              <li key={rule.id} className="border-b border-border py-1 last:border-0">
                {rule.category.name}
                {rule.sub_category ? ` / ${rule.sub_category.name}` : " (all)"} → {rule.team.name}
              </li>
            ))}
          </ul>
          <form onSubmit={handleCreateRoutingRule} className="mt-3 space-y-2">
            <select
              value={routingCategoryId}
              onChange={(event) => setRoutingCategoryId(event.target.value)}
              className="w-full rounded-md border border-border bg-background px-2 py-1 text-sm text-text-primary"
            >
              <option value="">Select category</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            <select
              value={routingTeamId}
              onChange={(event) => setRoutingTeamId(event.target.value)}
              className="w-full rounded-md border border-border bg-background px-2 py-1 text-sm text-text-primary"
            >
              <option value="">Select team</option>
              {teams.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
            <button type="submit" className="rounded-md bg-accent px-3 py-1 text-sm font-medium text-surface hover:opacity-90">
              Add routing rule
            </button>
          </form>
        </SectionCard>

        <SectionCard title="SLA rules">
          <ul className="space-y-1 text-sm">
            {slaRules.map((rule) => (
              <li key={rule.id} className="border-b border-border py-1 last:border-0">
                {rule.category.name} / {rule.priority}: {rule.first_response_minutes}m first response,{" "}
                {rule.resolution_minutes}m resolution
              </li>
            ))}
          </ul>
          <form onSubmit={handleCreateSlaRule} className="mt-3 space-y-2">
            <select
              value={slaCategoryId}
              onChange={(event) => setSlaCategoryId(event.target.value)}
              className="w-full rounded-md border border-border bg-background px-2 py-1 text-sm text-text-primary"
            >
              <option value="">Select category</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            <select
              value={slaPriority}
              onChange={(event) => setSlaPriority(event.target.value as IssuePriority)}
              className="w-full rounded-md border border-border bg-background px-2 py-1 text-sm text-text-primary"
            >
              {ALL_PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
            <div className="flex gap-2">
              <input
                type="number"
                min={1}
                value={slaFirstResponse}
                onChange={(event) => setSlaFirstResponse(Number(event.target.value))}
                className="w-1/2 rounded-md border border-border bg-background px-2 py-1 text-sm text-text-primary"
              />
              <input
                type="number"
                min={1}
                value={slaResolution}
                onChange={(event) => setSlaResolution(Number(event.target.value))}
                className="w-1/2 rounded-md border border-border bg-background px-2 py-1 text-sm text-text-primary"
              />
            </div>
            <p className="text-xs text-text-secondary">First response / resolution, in minutes.</p>
            <button type="submit" className="rounded-md bg-accent px-3 py-1 text-sm font-medium text-surface hover:opacity-90">
              Add SLA rule
            </button>
          </form>
        </SectionCard>

        <SectionCard title="Invite a resolver or admin">
          <p className="mb-3 text-xs text-text-secondary">
            The invited person sets their own password - you never choose or see it. Copy the activation link below
            and send it to them yourself (no email is sent automatically).
          </p>
          <form onSubmit={handleCreateInvite} className="flex flex-wrap items-end gap-2">
            <div>
              <label className="block text-xs text-text-secondary">Email</label>
              <input
                type="email"
                required
                value={inviteEmail}
                onChange={(event) => setInviteEmail(event.target.value)}
                className="rounded-md border border-border bg-background px-2 py-1 text-sm text-text-primary"
              />
            </div>
            <div>
              <label className="block text-xs text-text-secondary">Role</label>
              <select
                value={inviteRole}
                onChange={(event) => setInviteRole(event.target.value as "RESOLVER" | "ADMIN")}
                className="rounded-md border border-border bg-background px-2 py-1 text-sm text-text-primary"
              >
                <option value="RESOLVER">Resolver</option>
                <option value="ADMIN">Admin</option>
              </select>
            </div>
            {inviteRole === "RESOLVER" && (
              <div>
                <label className="block text-xs text-text-secondary">Team</label>
                <select
                  required
                  value={inviteTeamId}
                  onChange={(event) => setInviteTeamId(event.target.value)}
                  className="rounded-md border border-border bg-background px-2 py-1 text-sm text-text-primary"
                >
                  <option value="" disabled>
                    Select a team...
                  </option>
                  {teams.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </div>
            )}
            <button type="submit" className="rounded-md bg-accent px-3 py-1 text-sm font-medium text-surface hover:opacity-90">
              Create invite
            </button>
          </form>

          {lastCreatedInvite && (
            <div className="mt-4 rounded-md border border-accent bg-background p-3">
              <p className="text-xs font-medium text-text-primary">
                Invite created for {lastCreatedInvite.email} ({lastCreatedInvite.role}
                {lastCreatedInvite.team ? ` · ${lastCreatedInvite.team.name}` : ""}) - copy this link and send it to
                them:
              </p>
              <input
                readOnly
                value={lastCreatedInvite.activation_url}
                onFocus={(event) => event.target.select()}
                className="mt-2 w-full rounded-md border border-border bg-surface px-2 py-1 text-xs text-text-primary"
              />
            </div>
          )}

          {pendingInvites.length > 0 && (
            <div className="mt-4 overflow-x-auto">
              <p className="mb-1 text-xs font-medium text-text-secondary">Pending invites</p>
              <table className="w-full min-w-[320px] text-left text-sm">
                <thead className="text-xs uppercase tracking-wide text-text-secondary">
                  <tr>
                    <th className="py-1">Email</th>
                    <th className="py-1">Expires</th>
                  </tr>
                </thead>
                <tbody>
                  {pendingInvites.map((invite) => (
                    <tr key={invite.id} className="border-t border-border">
                      <td className="py-1">{invite.email}</td>
                      <td className="py-1">{new Date(invite.expires_at).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </SectionCard>

        <SectionCard title="Users">
          <div className="overflow-x-auto">
          <table className="w-full min-w-[480px] text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-text-secondary">
              <tr>
                <th className="py-1">Name</th>
                <th className="py-1">Role</th>
                <th className="py-1">Team</th>
                <th className="py-1">Active</th>
                <th className="py-1" />
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-t border-border">
                  <td className="py-1">{u.full_name}</td>
                  <td className="py-1">{u.role.name}</td>
                  <td className="py-1">{u.team?.name ?? "—"}</td>
                  <td className="py-1">{u.is_active ? "Yes" : "No"}</td>
                  <td className="py-1 text-right">
                    <button
                      onClick={() => handleToggleUserActive(u)}
                      className="mr-2 text-xs font-medium text-accent hover:underline"
                    >
                      {u.is_active ? "Disable" : "Enable"}
                    </button>
                    {u.role.name === "USER" && teams.length > 0 && (
                      <select
                        onChange={(event) => event.target.value && handlePromote(u.id, event.target.value)}
                        defaultValue=""
                        className="rounded-md border border-border bg-background px-1 py-0.5 text-xs text-text-primary"
                      >
                        <option value="" disabled>
                          Make resolver...
                        </option>
                        {teams.map((t) => (
                          <option key={t.id} value={t.id}>
                            {t.name}
                          </option>
                        ))}
                      </select>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </SectionCard>
      </div>
    </AppShell>
  );
}
