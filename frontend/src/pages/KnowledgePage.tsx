import { useKnowledge } from "../hooks/useKnowledge";
import { Button } from "../components/ui/Button";
import { Badge } from "../components/ui/Badge";
import { statusVariant } from "../components/ui/badgeVariants";
import { BookIcon } from "../components/ui/Icons";
import { EmptyState } from "../components/ui/EmptyState";

export function KnowledgePage() {
  const kb = useKnowledge();

  if (!kb.canViewKnowledge) {
    return (
      <div className="page">
        <h1>知识库管理</h1>
        <p>你没有查看知识库的权限。</p>
      </div>
    );
  }

  return (
    <section className="panel">
      <div className="panel__header">
        <div>
          <h3>知识库管理</h3>
          <p>导入文档并构建向量索引，供 RAG 检索使用</p>
        </div>
        <Button variant="secondary" onClick={() => void kb.loadKnowledgeDocs()}>
          刷新列表
        </Button>
      </div>

      {kb.error ? <p className="panel__error">{kb.error}</p> : null}

      <div className="upload-zone">
        <div className="upload-zone__icon">
          <BookIcon />
        </div>
        <div className="upload-zone__content">
          <label className="upload-zone__label">
            <span>导入知识文档</span>
            <span className="upload-zone__hint">支持 txt / md / pdf 格式</span>
            <input
              type="file"
              accept=".txt,.md,.pdf"
              disabled={!kb.canManageKnowledge}
              onChange={(e) => void kb.upload(e.target.files?.[0] || null)}
            />
          </label>
          <p className="upload-zone__status">
            {kb.uploadStatus || (kb.canManageKnowledge ? "点击选择文件上传" : "你没有导入权限")}
          </p>
        </div>
      </div>

      {kb.knowledgeDocs.length === 0 ? (
        <EmptyState icon={<BookIcon />} title="暂无知识文档" description="上传文档后将自动分块并建立向量索引" />
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>标题</th>
                <th>状态</th>
                <th>分块数</th>
                <th>更新时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {kb.knowledgeDocs.map((doc) => (
                <tr key={doc.id}>
                  <td className="data-table__title">{doc.title}</td>
                  <td>
                    <Badge variant={statusVariant(doc.status)}>{doc.status}</Badge>
                  </td>
                  <td>{doc.chunk_count}</td>
                  <td className="data-table__time">{new Date(doc.updated_at).toLocaleString()}</td>
                  <td>
                    <Button variant="ghost" disabled={!kb.canReindexKnowledge} onClick={() => void kb.reindex(doc.id)}>
                      重建索引
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
