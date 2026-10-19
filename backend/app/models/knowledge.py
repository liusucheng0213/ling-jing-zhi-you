import uuid
from sqlalchemy import Column, String, Text, Integer, ForeignKey, DateTime, func, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from .base import Base


class KnowledgeDocument(Base):
    """知识文档表"""
    __tablename__ = "knowledge_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(500), nullable=False)
    doc_type = Column(String(50), nullable=False)
    spot_id = Column(String(50), ForeignKey("spots.id"), nullable=True)
    content = Column(Text, nullable=False)
    content_html = Column(Text)
    source_file = Column(String(500))
    status = Column(String(20), default="draft")
    version = Column(Integer, default=1)
    metadata_json = Column(JSON, default=dict)
    lang = Column(String(10), default="zh")
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    published_at = Column(DateTime)

    chunks = relationship("KnowledgeChunk", back_populates="document", cascade="all, delete-orphan")


class KnowledgeChunk(Base):
    """知识片段表（pgvector向量检索）"""
    __tablename__ = "knowledge_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_documents.id"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    # embedding字段通过Alembic迁移添加（pgvector的vector类型）
    char_count = Column(Integer)
    token_count = Column(Integer)
    created_at = Column(DateTime, server_default=func.now())

    document = relationship("KnowledgeDocument", back_populates="chunks")
