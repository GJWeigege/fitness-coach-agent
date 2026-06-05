import { useCallback, useEffect, useState } from "react";
import { listKnowledgeDocuments, reindexDocument, uploadKnowledge } from "../api";
import { useAuth, usePermissions } from "../contexts/AuthContext";
import type { KnowledgeDocument } from "../types";

export function useKnowledge() {
  const { token } = useAuth();
  const { canViewKnowledge, canManageKnowledge, canReindexKnowledge } = usePermissions();
  const [knowledgeDocs, setKnowledgeDocs] = useState<KnowledgeDocument[]>([]);
  const [uploadStatus, setUploadStatus] = useState("");
  const [error, setError] = useState("");

  const loadKnowledgeDocs = useCallback(async () => {
    if (!token || !canViewKnowledge) return;
    try {
      setKnowledgeDocs(await listKnowledgeDocuments(token));
      setError("");
    } catch (err) {
      setError((err as Error).message);
    }
  }, [token, canViewKnowledge]);

  useEffect(() => {
    void loadKnowledgeDocs();
  }, [loadKnowledgeDocs]);

  async function upload(file: File | null) {
    if (!file || !token) return;
    setUploadStatus("上传中...");
    try {
      const res = await uploadKnowledge(token, file);
      setUploadStatus(`已入库：${res.title}（${res.chunks} 个分块）`);
      await loadKnowledgeDocs();
    } catch (err) {
      setUploadStatus((err as Error).message);
    }
  }

  async function reindex(docId: string) {
    if (!token) return;
    try {
      await reindexDocument(token, docId);
      await loadKnowledgeDocs();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return {
    knowledgeDocs,
    uploadStatus,
    error,
    loadKnowledgeDocs,
    upload,
    reindex,
    canManageKnowledge,
    canReindexKnowledge,
    canViewKnowledge,
  };
}
