import type { User } from "./auth";
import type { IssuePriority } from "./issue";

export interface AdminTeam {
  id: string;
  name: string;
  description: string | null;
  is_active: boolean;
  created_at: string;
}

export interface AdminSubCategory {
  id: string;
  name: string;
  is_active: boolean;
}

export interface AdminCategory {
  id: string;
  name: string;
  description: string | null;
  is_active: boolean;
  sub_categories: AdminSubCategory[];
}

export interface AdminRoutingRule {
  id: string;
  category: { id: string; name: string };
  sub_category: { id: string; name: string } | null;
  team: { id: string; name: string };
  is_active: boolean;
}

export interface AdminSLARule {
  id: string;
  category: { id: string; name: string };
  priority: IssuePriority;
  first_response_minutes: number;
  resolution_minutes: number;
  is_active: boolean;
}

export type { User as AdminUser };
