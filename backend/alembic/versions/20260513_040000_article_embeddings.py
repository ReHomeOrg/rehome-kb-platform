"""article_embeddings + pgvector extension

Revision ID: 0014_article_embeddings
Revises: 0013_audit_log
Create Date: 2026-05-13 04:00:00.000000

kb-search Stage 1 foundation (ADR-0010 #126).

Создаёт `vector` extension + таблицу `article_embeddings` с PK
`(article_id, chunk_index, embedding_model_id)` — поддерживает
blue-green re-embedding (новый model_id добавляет rows параллельно
с old, atomic switch когда coverage 100%).

INDICES:
- HNSW `(embedding vector_cosine_ops)` WITH (m=16, ef_construction=64) —
  основной retrieval index, cosine similarity.
- `(article_id, embedding_model_id)` — model bump scans (что доиндексить).

Сервер требует pgvector extension installed (Docker image
`pgvector/pgvector:pg16`). Stock `postgres:16` не имеет extension в pkg —
compose обновлён в этой же PR'е.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014_article_embeddings"
down_revision: str | None = "0013_audit_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgvector extension — idempotent (CREATE EXTENSION IF NOT EXISTS).
    # Требует pgvector/pgvector:pg16 image; на stock postgres:16 фейлится
    # loudly с "could not open extension control file".
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Raw SQL CREATE TABLE — alembic / SQLAlchemy не знают pgvector
    # `vector(N)` type из коробки, и ALTER TABLE ... TYPE vector
    # требует USING clause которое неудобно generate'ить. Raw SQL
    # яснее и точнее: column type, FK action, PK structure explicit.
    op.execute(
        """
        CREATE TABLE article_embeddings (
            article_id UUID NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            embedding_model_id VARCHAR(128) NOT NULL,
            embedding vector(1024) NOT NULL,
            char_start INTEGER NOT NULL,
            char_end INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (article_id, chunk_index, embedding_model_id)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE article_embeddings IS 'article chunk embeddings (ADR-0010, #126)'"
    )

    # HNSW index — основной retrieval путь. CONCURRENTLY не используем в
    # migration (alembic open's transaction; CONCURRENTLY требует
    # autocommit). Initial scale low — online rebuild будущая optimization.
    op.execute(
        "CREATE INDEX ix_article_embeddings_hnsw "
        "ON article_embeddings USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    # Index для model bump scans ("какие articles ещё не embedded под
    # new model?"). B-tree default.
    op.create_index(
        "ix_article_embeddings_article_model",
        "article_embeddings",
        ["article_id", "embedding_model_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_article_embeddings_article_model",
        table_name="article_embeddings",
    )
    op.execute("DROP INDEX IF EXISTS ix_article_embeddings_hnsw")
    op.drop_table("article_embeddings")
    # Extension drop оставляем opt-in — другие модули могут начать его
    # использовать. Operator при rollback всей платформы делает
    # `DROP EXTENSION vector` вручную если нужно.
