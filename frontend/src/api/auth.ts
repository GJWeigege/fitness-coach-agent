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
