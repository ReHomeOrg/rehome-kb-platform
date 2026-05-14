"""Background workers — отдельные processes за пределами FastAPI gateway.

Подмодули:
- `indexer/` — RAG embedding worker (#149, ADR-0010 §Stage 1).
  Runs in dedicated container с heavy HF deps.
"""
