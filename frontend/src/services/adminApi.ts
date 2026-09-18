import { apiRequest } from "./api";
import type { AdminCategory, AdminRoutingRule, AdminSLARule, AdminTeam, AdminUser } from "../types/admin";
import type { IssuePriority } from "../types/issue";

export function listTeams(token: string): Promise<AdminTeam[]> {
  return apiRequest<AdminTeam[]>("/api/v1/admin/teams", {}, token);
}

export function createTeam(token: string, name: string, description?: string): Promise<AdminTeam> {
  return apiRequest<AdminTeam>(
    "/api/v1/admin/teams",
    { method: "POST", body: JSON.stringify({ name, description: description ?? null }) },
    token,
  );
}

export function setTeamActive(token: string, teamId: string, isActive: boolean): Promise<AdminTeam> {
  return apiRequest<AdminTeam>(
    `/api/v1/admin/teams/${teamId}`,
    { method: "PATCH", body: JSON.stringify({ is_active: isActive }) },
    token,
  );
}

export function listCategories(token: string): Promise<AdminCategory[]> {
  return apiRequest<AdminCategory[]>("/api/v1/admin/categories", {}, token);
}

export function createCategory(token: string, name: string, description?: string): Promise<AdminCategory> {
  return apiRequest<AdminCategory>(
    "/api/v1/admin/categories",
    { method: "POST", body: JSON.stringify({ name, description: description ?? null }) },
    token,
  );
}

export function createSubCategory(token: string, categoryId: string, name: string): Promise<AdminCategory> {
  return apiRequest<AdminCategory>(
    `/api/v1/admin/categories/${categoryId}/sub-categories`,
    { method: "POST", body: JSON.stringify({ name }) },
    token,
  );
}

export function listRoutingRules(token: string): Promise<AdminRoutingRule[]> {
  return apiRequest<AdminRoutingRule[]>("/api/v1/admin/routing-rules", {}, token);
}

export function createRoutingRule(
  token: string,
  params: { categoryId: string; subCategoryId?: string; teamId: string },
): Promise<AdminRoutingRule> {
  return apiRequest<AdminRoutingRule>(
    "/api/v1/admin/routing-rules",
    {
      method: "POST",
      body: JSON.stringify({
        category_id: params.categoryId,
        sub_category_id: params.subCategoryId ?? null,
        team_id: params.teamId,
      }),
    },
    token,
  );
}

export function listSLARules(token: string): Promise<AdminSLARule[]> {
  return apiRequest<AdminSLARule[]>("/api/v1/admin/sla-rules", {}, token);
}

export function createSLARule(
  token: string,
  params: { categoryId: string; priority: IssuePriority; firstResponseMinutes: number; resolutionMinutes: number },
): Promise<AdminSLARule> {
  return apiRequest<AdminSLARule>(
    "/api/v1/admin/sla-rules",
    {
      method: "POST",
      body: JSON.stringify({
        category_id: params.categoryId,
        priority: params.priority,
        first_response_minutes: params.firstResponseMinutes,
        resolution_minutes: params.resolutionMinutes,
      }),
    },
    token,
  );
}

export function listUsers(token: string): Promise<AdminUser[]> {
  return apiRequest<AdminUser[]>("/api/v1/admin/users", {}, token);
}

export function updateUser(
  token: string,
  userId: string,
  params: { role?: string; teamId?: string; isActive?: boolean },
): Promise<AdminUser> {
  return apiRequest<AdminUser>(
    `/api/v1/admin/users/${userId}`,
    {
      method: "PATCH",
      body: JSON.stringify({
        role: params.role ?? null,
        team_id: params.teamId ?? null,
        is_active: params.isActive ?? null,
      }),
    },
    token,
  );
}
