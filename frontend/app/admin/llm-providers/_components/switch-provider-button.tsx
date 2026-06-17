"use client";

/**
 * Switch active LLM provider button (#265). PUT /admin/llm/active.
 *
 * Required reason + X-MFA-Token via Keycloak step-up flow (ADR-0019,
 * #336 backend / #337 frontend). На success → router.refresh().
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import MfaStepUpButton from "@/app/_components/mfa-step-up-button";
import { ApiError } from "@/lib/api/client";
import { setActiveLlmProvider } from "@/lib/api/admin-llm-providers";

interface Props {
  providerId: string;
}

export default function SwitchProviderButton({ providerId }: Props): JSX.Element {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [mfaToken, setMfaToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>();

  async function handleSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    if (!reason.trim()) {
      setError("Reason обязателен (audit trail).");
      setBusy(false);
      return;
    }
    if (!mfaToken.trim()) {
      setError("MFA token обязателен (нажмите кнопку step-up выше).");
      setBusy(false);
      return;
    }
    try {
      await setActiveLlmProvider(
        { provider_id: providerId, reason: reason.trim() },
        mfaToken.trim() || undefined,
      );
      setOpen(false);
      router.refresh();
    } catch (e) {
      if (e instanceof ApiError) {
        setError(`Ошибка ${e.status}: ${e.message}`);
      } else {
        setError("Не удалось переключить.");
      }
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-50"
      >
        Switch
      </button>
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-2 rounded-md border border-gray-200 bg-gray-50 p-3"
      aria-label={`Switch to ${providerId}`}
    >
      <div className="text-xs font-medium text-gray-700">
        Switch to <code className="font-mono">{providerId}</code>
      </div>
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-gray-600">Reason *</span>
        <input
          type="text"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          maxLength={500}
          className="rounded-md border border-gray-300 px-2 py-1 text-xs"
          aria-label="Switch reason"
          placeholder="A/B test до пятницы"
        />
      </label>
      <div className="flex flex-col gap-1 text-xs">
        <span className="text-gray-600">
          Step-up MFA (acr=2 required для switch)
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
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={busy}
          className="rounded-md bg-brand px-2 py-1 text-xs font-medium text-white hover:bg-brand-hover disabled:opacity-50"
        >
          {busy ? "Переключение…" : "Подтвердить"}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          disabled={busy}
          className="rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-50"
        >
          Отмена
        </button>
      </div>
    </form>
  );
}
