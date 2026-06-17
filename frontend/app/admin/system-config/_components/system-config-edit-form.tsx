"use client";

/**
 * System config edit form (#266). PATCH /admin/system-config (backend
 * #264, ADR-0019).
 *
 * Mutable keys (см. backend allowlist):
 * - llm_fallback_provider (text)
 * - moderation.auto_publish_threshold (float 0..1 nullable)
 * - feature_flags.{rag_enabled, webhook_worker_enabled, metrics_enabled}
 *   (boolean toggles)
 *
 * llm_provider — отдельный UX через /admin/llm-providers Switch button
 * (#265), здесь не редактируется.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import MfaStepUpButton from "@/app/_components/mfa-step-up-button";
import { ApiError } from "@/lib/api/client";
import {
  patchSystemConfig,
  type SystemConfigPatch,
} from "@/lib/api/admin-system-config";
import type { SystemConfig } from "@/lib/api/types";

interface Props {
  initial: SystemConfig;
}

function thresholdToInput(v: number | null | undefined): string {
  if (v === null || v === undefined) return "";
  return String(v);
}

function parseThreshold(s: string): number | null {
  const trimmed = s.trim();
  if (trimmed === "") return null;
  const n = Number(trimmed);
  if (Number.isNaN(n)) return Number.NaN;
  return n;
}

export default function SystemConfigEditForm({ initial }: Props): JSX.Element {
  const router = useRouter();
  const [fallback, setFallback] = useState(
    initial.llm_config.fallback_provider ?? "",
  );
  const [threshold, setThreshold] = useState(
    thresholdToInput(initial.moderation.auto_publish_threshold),
  );
  const [ragEnabled, setRagEnabled] = useState(
    Boolean(initial.feature_flags.rag ?? false),
  );
  const [webhookEnabled, setWebhookEnabled] = useState(
    Boolean(initial.feature_flags.webhook_worker ?? false),
  );
  const [metricsEnabled, setMetricsEnabled] = useState(
    Boolean(initial.feature_flags.metrics_endpoint ?? false),
  );
  const [mfaToken, setMfaToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>();
  const [success, setSuccess] = useState(false);

  async function handleSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    setSuccess(false);

    const patch: SystemConfigPatch = {};

    const fallbackTrimmed = fallback.trim();
    const initialFallback = initial.llm_config.fallback_provider ?? "";
    if (fallbackTrimmed !== initialFallback) {
      patch["llm_fallback_provider"] = fallbackTrimmed || null;
    }

    const parsedThreshold = parseThreshold(threshold);
    if (Number.isNaN(parsedThreshold)) {
      setError("auto_publish_threshold должен быть числом или пустой строкой.");
      setBusy(false);
      return;
    }
    if (parsedThreshold !== initial.moderation.auto_publish_threshold) {
      patch["moderation.auto_publish_threshold"] = parsedThreshold;
    }

    if (ragEnabled !== Boolean(initial.feature_flags.rag ?? false)) {
      patch["feature_flags.rag_enabled"] = ragEnabled;
    }
    if (
      webhookEnabled !== Boolean(initial.feature_flags.webhook_worker ?? false)
    ) {
      patch["feature_flags.webhook_worker_enabled"] = webhookEnabled;
    }
    if (
      metricsEnabled !== Boolean(initial.feature_flags.metrics_endpoint ?? false)
    ) {
      patch["feature_flags.metrics_enabled"] = metricsEnabled;
    }

    if (Object.keys(patch).length === 0) {
      setBusy(false);
      return;
    }
    if (!mfaToken.trim()) {
      setError("MFA token обязателен (нажмите кнопку step-up выше).");
      setBusy(false);
      return;
    }

    try {
      await patchSystemConfig(patch, mfaToken.trim() || undefined);
      setSuccess(true);
      router.refresh();
    } catch (e) {
      if (e instanceof ApiError) {
        setError(`Ошибка ${e.status}: ${e.message}`);
      } else {
        setError("Не удалось сохранить.");
      }
    }
    setBusy(false);
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="mb-6 space-y-4 rounded-md border border-gray-200 bg-white p-4"
      aria-label="System config edit"
    >
      <h2 className="text-sm font-medium text-gray-700">
        Изменить настройки (PATCH overlay)
      </h2>
      <p className="text-xs text-gray-500">
        Allowlist per ADR-0019. llm_provider — через /admin/llm-providers
        Switch button.
      </p>

      <label className="flex flex-col gap-1 text-xs">
        <span className="text-gray-600">llm_fallback_provider</span>
        <input
          type="text"
          value={fallback}
          onChange={(e) => setFallback(e.target.value)}
          maxLength={64}
          className="w-48 rounded-md border border-gray-300 px-2 py-1 text-xs"
          aria-label="llm_fallback_provider"
          placeholder="напр. mock (или пусто)"
        />
      </label>

      <label className="flex flex-col gap-1 text-xs">
        <span className="text-gray-600">
          moderation.auto_publish_threshold (0..1 или пусто)
        </span>
        <input
          type="text"
          value={threshold}
          onChange={(e) => setThreshold(e.target.value)}
          maxLength={20}
          className="w-32 rounded-md border border-gray-300 px-2 py-1 text-xs"
          aria-label="auto_publish_threshold"
          placeholder="0.85"
        />
      </label>

      <fieldset>
        <legend className="text-xs text-gray-600">Feature flags</legend>
        <div className="mt-1 space-y-1 text-xs">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={ragEnabled}
              onChange={(e) => setRagEnabled(e.target.checked)}
              aria-label="rag_enabled"
            />
            <code className="font-mono">rag_enabled</code>
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={webhookEnabled}
              onChange={(e) => setWebhookEnabled(e.target.checked)}
              aria-label="webhook_worker_enabled"
            />
            <code className="font-mono">webhook_worker_enabled</code>
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={metricsEnabled}
              onChange={(e) => setMetricsEnabled(e.target.checked)}
              aria-label="metrics_enabled"
            />
            <code className="font-mono">metrics_enabled</code>
          </label>
        </div>
      </fieldset>

      <div className="flex flex-col gap-1 text-xs">
        <span className="text-gray-600">
          Step-up MFA (acr=2 token required для PATCH)
        </span>
        <MfaStepUpButton
          onTokenAcquired={setMfaToken}
          hasToken={mfaToken.length > 0}
        />
      </div>

      {error ? (
        <div
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-2 text-xs text-red-900"
        >
          {error}
        </div>
      ) : null}
      {success ? (
        <div
          role="status"
          className="rounded-md border border-green-200 bg-green-50 p-2 text-xs text-green-900"
        >
          Сохранено.
        </div>
      ) : null}

      <button
        type="submit"
        disabled={busy}
        className="rounded-md bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-hover disabled:opacity-50"
      >
        {busy ? "Сохранение…" : "Сохранить"}
      </button>
    </form>
  );
}
