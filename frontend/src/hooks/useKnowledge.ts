import { useCallback, useEffect, useRef, useState } from "react";
import { listKnowledgeDocuments, reindexAllDocuments, reindexDocument, uploadKnowledge } from "../api";
import { useAuth, usePermissions } from "../contexts/AuthContext";
import type { KnowledgeDocument, KnowledgeReindexAllResponse } from "../types";

const REINDEX_POLL_INTERVAL_MS = 3000;
const REINDEX_POLL_MAX_ATTEMPTS = 60;

function hasActiveIngestOrReindex(docs: KnowledgeDocument[]): boolean {
  return docs.some((doc) => doc.status === "pending" || doc.status === "reindexing");
}

function buildReindexAllStatus(res: KnowledgeReindexAllResponse): string {
  const skippedNote =
    res.skipped.length > 0 ? `，跳过 ${res.skipped.length} 个（源文件缺失或处理中）` : "";
  if (res.queued_count === 0) {
    return res.skipped.length > 0 ? `无需排队${skippedNote}` : "没有可重建索引的文档";
  }
  return `已排队 ${res.queued_count} 个文档${skippedNote}，后台处理中…`;
}

function summarizeReindexOutcome(docs: KnowledgeDocument[]): string {
  const failedCount = docs.filter((doc) => doc.status === "failed").length;
  if (failedCount > 0) {
    return `，${failedCount} 个失败，请查看列表`;
  }
  return "，已全部完成";
}

function isReindexConflictMessage(message: string): boolean {
  return message.includes("正在进行中") || message.includes("正在重建索引");
}

export function useKnowledge() {
  const { token } = useAuth();
  const { canViewKnowledge, canManageKnowledge, canReindexKnowledge } = usePermissions();
  const [knowledgeDocs, setKnowledgeDocs] = useState<KnowledgeDocument[]>([]);
  const [uploadStatus, setUploadStatus] = useState("");
  const [reindexAllStatus, setReindexAllStatus] = useState("");
  const [reindexAllLoading, setReindexAllLoading] = useState(false);
  const [reindexAllPolling, setReindexAllPolling] = useState(false);
  const [error, setError] = useState("");
  const pollGenerationRef = useRef(0);

  const loadKnowledgeDocs = useCallback(async () => {
    if (!token || !canViewKnowledge) return [];
    try {
      const docs = await listKnowledgeDocuments(token);
      setKnowledgeDocs(docs);
      setError("");
      return docs;
    } catch (err) {
      setError((err as Error).message);
      return [];
    }
  }, [token, canViewKnowledge]);

  useEffect(() => {
    void loadKnowledgeDocs();
  }, [loadKnowledgeDocs]);

  useEffect(() => {
    return () => {
      pollGenerationRef.current += 1;
    };
  }, []);

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

  async function pollUntilReindexComplete(generation: number) {
    if (!token) {
      setReindexAllPolling(false);
      return;
    }

    try {
      for (let attempt = 0; attempt < REINDEX_POLL_MAX_ATTEMPTS; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, REINDEX_POLL_INTERVAL_MS));
        if (pollGenerationRef.current !== generation) {
          return;
        }

        const docs = await loadKnowledgeDocs();
        if (pollGenerationRef.current !== generation) {
          return;
        }

        if (!hasActiveIngestOrReindex(docs)) {
          setReindexAllStatus(
            (prev) => `${prev.replace(/，后台处理中…$/, "")}${summarizeReindexOutcome(docs)}`
          );
          return;
        }
      }

      if (pollGenerationRef.current === generation) {
        setReindexAllStatus((prev) =>
          `${prev.replace(/，后台处理中…$/, "")}（部分文档仍在处理中，请稍后刷新）`
        );
      }
    } finally {
      if (pollGenerationRef.current === generation) {
        setReindexAllPolling(false);
      }
    }
  }

  async function reindexAll() {
    if (!token || reindexAllLoading || reindexAllPolling) return;
    setReindexAllLoading(true);
    setReindexAllStatus("正在提交全量重建索引…");
    try {
      const res = await reindexAllDocuments(token);
      setReindexAllStatus(buildReindexAllStatus(res));
      await loadKnowledgeDocs();
      setError("");
      if (res.queued_count > 0) {
        const generation = pollGenerationRef.current;
        setReindexAllPolling(true);
        void pollUntilReindexComplete(generation);
      }
    } catch (err) {
      const message = (err as Error).message;
      if (isReindexConflictMessage(message)) {
        setReindexAllStatus(message);
        setError("");
      } else {
        setReindexAllStatus("");
        setError(message);
      }
    } finally {
      setReindexAllLoading(false);
    }
  }

  const reindexAllBusy = reindexAllLoading || reindexAllPolling;

  return {
    knowledgeDocs,
    uploadStatus,
    reindexAllStatus,
    reindexAllLoading,
    reindexAllPolling,
    reindexAllBusy,
    error,
    loadKnowledgeDocs,
    upload,
    reindex,
    reindexAll,
    canManageKnowledge,
    canReindexKnowledge,
    canViewKnowledge,
  };
}
