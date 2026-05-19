"""Popular-query daily aggregator worker (#220).

ТЗ §5.1: `search.popular_query` event — «запрос стал часто повторяющимся
без ответа (раз в день)». Worker scan'ит `search_query_log` за окно
(default 24h), группирует unanswered queries, и для тех что crossed
`min_count` — emit'ит ОДИН webhook event с payload `{queries: [...]}`
per ТЗ spec.
"""
