import { API_BASE, apiFetch, buildHeaders } from "./client";

export type FitnessProfile = {
  user_id: string;
  age: number | null;
  sex: string | null;
  height_cm: number | null;
  weight_kg: number | null;
  goals: string[] | null;
  experience_level: string;
  injuries: string[] | null;
  equipment: string[] | null;
  diet_preference: string | null;
  updated_at: string | null;
};

export type FitnessProfileUpdate = {
  age?: number | null;
  sex?: string | null;
  height_cm?: number | null;
  weight_kg?: number | null;
  goals?: string[] | null;
  experience_level?: string | null;
  injuries?: string[] | null;
  equipment?: string[] | null;
  diet_preference?: string | null;
};

export type TrainingLog = {
  id: string;
  session_date: string;
  activity_type: string;
  duration_min: number;
  intensity: string;
  notes: string | null;
  created_at: string;
};

export type TrainingLogCreate = {
  session_date: string;
  activity_type: string;
  duration_min: number;
  intensity: string;
  notes?: string | null;
};

export async function fetchProfile(token: string): Promise<FitnessProfile> {
  return apiFetch(`${API_BASE}/profile`, {
    headers: buildHeaders(token),
  });
}

export async function updateProfile(token: string, payload: FitnessProfileUpdate): Promise<FitnessProfile> {
  return apiFetch(`${API_BASE}/profile`, {
    method: "PUT",
    headers: buildHeaders(token, { "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
}

export async function listTrainingLogs(token: string): Promise<TrainingLog[]> {
  const data = await apiFetch<{ logs?: TrainingLog[] }>(`${API_BASE}/profile/training-logs`, {
    headers: buildHeaders(token),
  });
  return data.logs || [];
}

export async function createTrainingLog(token: string, payload: TrainingLogCreate): Promise<TrainingLog> {
  return apiFetch(`${API_BASE}/profile/training-logs`, {
    method: "POST",
    headers: buildHeaders(token, { "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
}
