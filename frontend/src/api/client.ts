export const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export function buildHeaders(token?: string, extra?: HeadersInit): HeadersInit {
  return {
    ...(extra || {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

function extractErrorMessage(text: string, fallback: string): string {
  if (!text) return fallback;
  try {
    const data = JSON.parse(text) as { detail?: unknown };
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) {
      return data.detail
        .map((item) => {
          if (typeof item === "string") return item;
          if (item && typeof item === "object" && "msg" in item) {
            return String((item as { msg: unknown }).msg);
          }
          return JSON.stringify(item);
        })
        .join("; ");
    }
  } catch {
    // not JSON
  }
  return text;
}

export async function parseError(response: Response, fallback: string): Promise<string> {
  try {
    const text = await response.text();
    return extractErrorMessage(text, fallback);
  } catch {
    return fallback;
  }
}

export async function apiFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    throw new Error(await parseError(response, "Request failed"));
  }
  return response.json();
}
