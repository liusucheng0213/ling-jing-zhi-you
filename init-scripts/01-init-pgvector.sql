-- PostgreSQL启动时自动执行
-- 安装pgvector扩展

CREATE EXTENSION IF NOT EXISTS vector;

-- 验证安装
SELECT * FROM pg_extension WHERE extname = 'vector';
