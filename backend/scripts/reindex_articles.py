"""Direct re-index for imported articles (bypass admin_task flow).

Calls IndexerService.reindex_all_articles напрямую с MockEmbeddingProvider
(deterministic SHA pseudo-embeddings — для UI demo достаточно; production
будет HF model через embedding_provider=hf).
"""

from __future__ import annotations

import asyncio
import sys

# Add backend src to path
sys.path.insert(0, "/home/evgeniy/projects/rehome-kb-platform/backend")

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://kb:kb@localhost:5432/rehome_kb")
os.environ.setdefault("RAG_ENABLED", "true")
os.environ.setdefault("EMBEDDING_PROVIDER", "mock")

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api.articles.repository import ArticleRepository
from src.api.search.embeddings import MockEmbeddingProvider
from src.api.search.indexer import IndexerService
from src.api.search.repository import EmbeddingRepository


async def main() -> int:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            article_repo = ArticleRepository(session)
            indexer = IndexerService(EmbeddingRepository(session), MockEmbeddingProvider())
            result = await indexer.reindex_all_articles(
                article_repo.iter_published_for_reindex(),
            )
            await session.commit()
            print(
                f"OK: articles_processed={result.articles_processed}, "
                f"chunks={result.chunks_total}, errors={result.errors_total}"
            )
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
