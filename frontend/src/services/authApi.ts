import { apiRequest } from "./api";
import type { AuthResponse, User } from "../types/auth";

export function register(email: string, password: string, fullName: string): Promise<User> {
  return apiRequest<User>("/api/v1/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, full_name: fullName }),
  });
}

export type LoginContext = "student" | "resolver" | "admin";

export function login(email: string, password: string, loginContext?: LoginContext): Promise<AuthResponse> {
  return apiRequest<AuthResponse>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password, login_context: loginContext }),
  });
}

export function getCurrentUser(token: string): Promise<User> {
  return apiRequest<User>("/api/v1/auth/me", {}, token);
}

export function logout(token: string): Promise<void> {
  return apiRequest<void>("/api/v1/auth/logout", { method: "POST" }, token);
}
