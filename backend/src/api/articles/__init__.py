"""Articles domain — read API над статьями help-центра и wiki.

См. ПЗ «API базы знаний v1.3» раздел 3.2 (Articles endpoints) и
ADR-0003 (storage-level access_level filter — критический инвариант).
"""

from src.api.articles.models import Article
from src.api.articles.repository import ArticleRepository

__all__ = ["Article", "ArticleRepository"]
