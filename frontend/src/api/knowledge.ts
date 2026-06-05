import { API_BASE, apiFetch, buildHeaders } from "./client";
import type { KnowledgeDocument } from "../types";

export async function uploadKnowledge(
  token: string,
  file: File
): Promise<{ document_id: string; chunks: number; title: string }> {
  const form = new FormData();
  form.append("file", file);
  return apiFetch(`${API_BASE}/knowledge/upload`, {
    method: "POST",
    headers: buildHeaders(token),
    body: form,
  });
}

export async function listKnowledgeDocuments(token: string): Promise<KnowledgeDocument[]> {
  const data = await apiFetch<{ documents?: KnowledgeDocument[] }>(`${API_BASE}/knowledge/documents`, {
    headers: buildHeaders(token),
  });
  return data.documents || [];
}

export async function reindexDocument(
  token: string,
  documentId: string
): Promise<{ document_id: string; chunks: number; title: string }> {
  return apiFetch(`${API_BASE}/knowledge/documents/${documentId}/reindex`, {
    method: "POST",
    headers: buildHeaders(token),
  });
}
