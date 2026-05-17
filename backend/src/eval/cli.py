"""Eval CLI — argparse entrypoint для batch run (ADR-0013).

Usage:

    python -m src.eval.cli \\
        --provider mock \\
        --judge mock \\
        --dataset tests/eval/golden.jsonl \\
        --out reports/eval-$(date +%Y%m%d-%H%M%S).json

Поддерживаемые providers:
- `mock` — MockProvider (echo, для smoke testing pipeline'а)
- `vllm` — VLLMProvider (требует LLM_VLLM_URL env)
- `gigachat` — GigaChatProvider (требует LLM_GIGACHAT_CLIENT_ID / _SECRET)
- `yandex_gpt` — YandexGptProvider (требует LLM_YANDEX_API_KEY / _FOLDER_ID)

Поддерживаемые judges:
- `mock` — MockJudge (heuristic-based, deterministic)
- `llm` — LLMJudge (использует --judge-provider для оценки)

Для `--judge llm` нужен **отдельный** provider (рекомендуется сильнее
системного — например, gigachat-judge оценивает yandex_gpt-system).
Указывается через `--judge-provider`.

Exit codes:
- 0 — run завершён успешно, отчёт записан
- 1 — invalid arguments / dataset не найден / Pydantic validation fail
- 2 — provider/judge construction fail
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from src.api.chat.llm.base import LLMProvider
from src.api.chat.llm.mock import MockProvider
from src.api.config import get_settings
from src.eval.dataset import dataset_sha256, load_dataset
from src.eval.judge import Judge, LLMJudge, MockJudge
from src.eval.report import new_report
from src.eval.runner import run_dataset

logger = logging.getLogger(__name__)


_PROVIDERS: dict[str, str] = {
    "mock": "MockProvider — echo, для smoke testing",
    "vllm": "VLLMProvider — self-hosted vLLM endpoint",
    "gigachat": "GigaChatProvider — Sber RU sovereign",
    "yandex_gpt": "YandexGptProvider — Yandex Cloud RU sovereign",
}

_JUDGES: dict[str, str] = {
    "mock": "MockJudge — heuristic-based, deterministic",
    "llm": "LLMJudge — использует --judge-provider для оценки",
}


def build_provider(name: str) -> LLMProvider:
    """Factory с честным error на unsupported провайдере.

    Reads config через `get_settings()` для credentials / URLs. Fail-fast
    если required env vars отсутствуют (см. config.py для list).
    """
    settings = get_settings()
    if name == "mock":
        return MockProvider()
    if name == "vllm":
        # Lazy import — vllm depends на httpx настройки в config.
        from src.api.chat.llm.vllm import VLLMProvider

        return VLLMProvider(
            url=settings.llm_vllm_url,
            model=settings.llm_vllm_model,
            timeout_seconds=settings.llm_vllm_timeout_seconds,
            api_key=settings.llm_vllm_api_key,
        )
    if name == "gigachat":
        from src.api.chat.llm.gigachat import GigaChatProvider

        if not settings.llm_gigachat_client_id or not settings.llm_gigachat_client_secret:
            raise ValueError(
                "provider=gigachat requires LLM_GIGACHAT_CLIENT_ID "
                "and LLM_GIGACHAT_CLIENT_SECRET env vars"
            )
        return GigaChatProvider(
            client_id=settings.llm_gigachat_client_id,
            client_secret=settings.llm_gigachat_client_secret,
            oauth_url=settings.llm_gigachat_oauth_url,
            base_url=settings.llm_gigachat_base_url,
            model=settings.llm_gigachat_model,
            scope=settings.llm_gigachat_scope,
            timeout_seconds=settings.llm_gigachat_timeout_seconds,
            verify_ssl=settings.llm_gigachat_verify_ssl,
        )
    if name == "yandex_gpt":
        from src.api.chat.llm.yandex_gpt import YandexGptProvider

        if not settings.llm_yandex_api_key or not settings.llm_yandex_folder_id:
            raise ValueError(
                "provider=yandex_gpt requires LLM_YANDEX_API_KEY "
                "and LLM_YANDEX_FOLDER_ID env vars"
            )
        return YandexGptProvider(
            api_key=settings.llm_yandex_api_key,
            folder_id=settings.llm_yandex_folder_id,
            base_url=settings.llm_yandex_base_url,
            model=settings.llm_yandex_model,
            model_version=settings.llm_yandex_model_version,
            timeout_seconds=settings.llm_yandex_timeout_seconds,
        )
    raise ValueError(f"Неизвестный provider '{name}'. Поддерживается: {list(_PROVIDERS)}")


def build_judge(name: str, *, judge_provider: str | None = None) -> Judge:
    """Factory для judge.

    `--judge llm` требует `judge_provider` — отдельный LLM-провайдер для
    оценки (рекомендуется сильнее системного, например gigachat-pro либо
    yandexgpt-pro).
    """
    if name == "mock":
        return MockJudge()
    if name == "llm":
        if judge_provider is None:
            raise ValueError("--judge llm requires --judge-provider to be specified")
        provider = build_provider(judge_provider)
        return LLMJudge(provider=provider, model_name=judge_provider)
    raise ValueError(f"Неизвестный judge '{name}'. Поддерживается: {list(_JUDGES)}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.eval.cli",
        description="Eval-стенд: прогон LLM-провайдера на размеченном dataset'е (ADR-0013).",
    )
    parser.add_argument(
        "--provider",
        required=True,
        choices=list(_PROVIDERS),
        help="LLM provider, " + "; ".join(f"{k}={v}" for k, v in _PROVIDERS.items()),
    )
    parser.add_argument(
        "--judge",
        required=True,
        choices=list(_JUDGES),
        help="Judge для scoring'а, " + "; ".join(f"{k}={v}" for k, v in _JUDGES.items()),
    )
    parser.add_argument(
        "--judge-provider",
        required=False,
        choices=list(_PROVIDERS),
        default=None,
        help="LLM provider для --judge llm (рекомендуется отличный от --provider).",
    )
    parser.add_argument(
        "--dataset",
        required=True,
        type=Path,
        help="Путь к JSONL dataset'у (см. ADR-0013 §2 schema)",
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Путь для JSON report'а (parent dirs создаются автоматически)",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    """Core async logic — separated для testability."""
    try:
        pairs = load_dataset(args.dataset)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("eval.cli.dataset_error", extra={"error": str(exc)})
        sys.stderr.write(f"Dataset error: {exc}\n")
        return 1

    try:
        provider = build_provider(args.provider)
        judge = build_judge(args.judge, judge_provider=args.judge_provider)
    except (ValueError, NotImplementedError) as exc:
        logger.error("eval.cli.construct_error", extra={"error": str(exc)})
        sys.stderr.write(f"Provider/Judge error: {exc}\n")
        return 2

    sha = dataset_sha256(args.dataset)
    logger.info(
        "eval.cli.start",
        extra={
            "provider": args.provider,
            "judge": args.judge,
            "judge_provider": args.judge_provider,
            "dataset": str(args.dataset),
            "dataset_sha256": sha,
            "pair_count": len(pairs),
        },
    )

    results = await run_dataset(
        pairs,
        provider,
        provider_name=args.provider,
        judge=judge,
    )

    report = new_report(
        provider=args.provider,
        judge=args.judge,
        dataset_path=args.dataset,
        dataset_sha256=sha,
        per_pair=results,
    )
    report.save(args.out)
    logger.info(
        "eval.cli.done",
        extra={
            "run_id": report.run_id,
            "out": str(args.out),
            "pair_count": report.aggregate.pair_count,
            "error_count": report.aggregate.error_count,
        },
    )
    sys.stdout.write(
        f"Report saved: {args.out}\n"
        f"  run_id={report.run_id}\n"
        f"  pairs={report.aggregate.pair_count} "
        f"errors={report.aggregate.error_count}\n"
        f"  latency_p50={report.aggregate.latency_p50:.3f}s "
        f"p95={report.aggregate.latency_p95:.3f}s\n"
        f"  citation_accuracy_avg={report.aggregate.citation_accuracy_avg:.3f}\n"
        f"  composite_avg={report.aggregate.composite_avg}\n"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point — returns exit code."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
