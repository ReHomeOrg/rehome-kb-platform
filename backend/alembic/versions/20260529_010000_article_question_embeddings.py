"""article_question_embeddings — Q&A в RAG corpus (ТЗ Чат-поиск §«корпуса»).

Revision ID: 0033_article_question_embeddings
Revises: 0032_article_questions
Create Date: 2026-05-29 01:00:00.000000

ANSWERED article_questions становятся retrievable через RAG: question +
answer indexed как single chunk (короткие тексты, chunking не нужен —
question typically 1-2 предложения, answer 1-3 абзаца).

Schema (mirror'ит article_embeddings структуру; raw SQL для pgvector
type — alembic / SQLAlchemy не знают `vector(N)` нативно, та же
причина что и в migration 0014):

- `article_question_id UUID FK article_questions(id) ON DELETE CASCADE`
- `embedding_model_id VARCHAR(128)` — blue-green re-embedding key
- `embedding vector(1024) NOT NULL`
- `text_indexed TEXT NOT NULL` — материализованный (question + answer)
  после PII масок (см. ФЗ-152 ниже). Хранится здесь т.к. raw text может
  содержать user PII; retrieval подаёт `text_indexed` в LLM context.
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- PK `(article_question_id, embedding_model_id)`

Indexes:
- `ix_article_question_embeddings_hnsw` (HNSW vector_cosine_ops, m=16
  ef=64) — mirror ArticleEmbedding config.
- `ix_article_question_embeddings_model` (embedding_model_id) — model
  bump cleanup scans.

ФЗ-152 invariants:
- `text_indexed` хранит уже masked (mask_pii) (question + answer). User
  query body может содержать phone/email; persisted masked'ом чтобы
  retrieval не leak'нул raw PII в LLM context.
- access_level — НЕ хранится на уровне embeddings (ADR-0003 inherit
  через JOIN article_questions → articles). Single source of truth.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0033_article_question_embeddings"
down_revision: str | None = "0032_article_questions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgvector extension already enabled by migration 0014; no-op
    # CREATE EXTENSION IF NOT EXISTS — defence-in-depth для fresh
    # databases куда катят миграции с этой.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute(
        """
        CREATE TABLE article_question_embeddings (
            article_question_id UUID NOT NULL REFERENCES article_questions(id) ON DELETE CASCADE,
            embedding_model_id VARCHAR(128) NOT NULL,
            embedding vector(1024) NOT NULL,
            text_indexed TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (article_question_id, embedding_model_id)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE article_question_embeddings IS "
        "'Q&A RAG corpus (ТЗ Чат-поиск, 2026-05-29)'"
    )

    op.execute(
        "CREATE INDEX ix_article_question_embeddings_hnsw "
        "ON article_question_embeddings USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    op.create_index(
        "ix_article_question_embeddings_model",
        "article_question_embeddings",
        ["embedding_model_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_article_question_embeddings_model",
        table_name="article_question_embeddings",
    )
    op.execute("DROP INDEX IF EXISTS ix_article_question_embeddings_hnsw")
    op.drop_table("article_question_embeddings")
