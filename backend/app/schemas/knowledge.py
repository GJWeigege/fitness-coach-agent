import uuid
from datetime import datetime

from pydantic import BaseModel


class KnowledgeUploadResponse(BaseModel):
    document_id: uuid.UUID
    chunks: int
    title: str


class KnowledgeDocumentItem(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    created_at: datetime
    updated_at: datetime
    chunk_count: int


class KnowledgeDocumentListResponse(BaseModel):
    documents: list[KnowledgeDocumentItem]
