import { API_BASE, apiFetch, buildHeaders } from "./client";
import type { UserProfile } from "../types";

export async function login(payload: {
  username: string;
  password: string;
}): Promise<{ access_token: string; user: UserProfile }> {
  return apiFetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function register(payload: {
  username: string;
  password: string;
}): Promise<{ access_token: string; user: UserProfile }> {
  return apiFetch(`${API_BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function fetchMe(token: string): Promise<UserProfile> {
  return apiFetch(`${API_BASE}/auth/me`, { headers: buildHeaders(token) });
}

export async function fetchPermissionMatrix(token: string): Promise<Record<string, string[]>> {
  const data = await apiFetch<{ roles?: Record<string, string[]> }>(`${API_BASE}/auth/permissions`, {
    headers: buildHeaders(token),
  });
  return data.roles || {};
}

export async function fetchUsers(token: string): Promise<UserProfile[]> {
  const data = await apiFetch<{ users?: UserProfile[] }>(`${API_BASE}/auth/users`, {
    headers: buildHeaders(token),
  });
  return data.users || [];
}

export async function createUser(
  token: string,
  payload: { username: string; password: string; role: string; custom_permissions?: string[] }
): Promise<UserProfile> {
  return apiFetch(`${API_BASE}/auth/users`, {
    method: "POST",
    headers: buildHeaders(token, { "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
}

export async function updateUser(
  token: string,
  userId: string,
  payload: { role?: string; custom_permissions?: string[]; is_active?: boolean }
): Promise<UserProfile> {
  return apiFetch(`${API_BASE}/auth/users/${userId}`, {
    method: "PATCH",
    headers: buildHeaders(token, { "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
}
