"""Categories module — нормализованное дерево категорий с article_count.

В отличие от tags (агрегация JSONB в articles), categories хранятся в
отдельной таблице с self-referential parent_id для иерархии. Связь с
articles — по string-полю `articles.category = categories.slug` (без
FK на этапе E2.7; FK добавится при первом admin CRUD эпике).
"""
