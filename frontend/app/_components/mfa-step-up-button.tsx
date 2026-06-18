"use client";

/**
 * MFA step-up button (ADR-0019 §«MFA»).
 *
 * Reusable trigger для acr=2 token acquisition. Wraps `requestStepUpToken`
 * с UI states (idle / requesting / acquired / error).
 *
 * Caller provides `onTokenAcquired` callback — receives short-lived
 * access_token (acr=2). Caller responsible за threading через X-MFA-Token
 * header в API call. Token не persisted в localStorage / sessionStorage
 * (ephemeral).
 */

import { useState } from "react";

import { StepUpError, requestStepUpToken } from "@/lib/auth/step-up";

interface Props {
  onTokenAcquired: (token: string) => void;
  /** Optional label override (default: «Получить MFA token (acr=2)»). */
  label?: string;
  /** True if a token is already acquired — button shows ✓ state. */
  hasToken?: boolean;
}

type State = "idle" | "requesting" | "error";

function describeError(err: unknown): string {
  if (err instanceof StepUpError) return err.message;
  return err instanceof Error ? err.message : "Unknown step-up error";
}

export default function MfaStepUpButton({
  onTokenAcquired,
  label,
  hasToken = false,
}: Props): JSX.Element {
  const [state, setState] = useState<State>("idle");
  const [error, setError] = useState<string | null>(null);

  const handleClick = async (): Promise<void> => {
    if (state === "requesting") return;
    setState("requesting");
    setError(null);
    try {
      const token = await requestStepUpToken();
      onTokenAcquired(token);
      setState("idle");
    } catch (err) {
      setError(describeError(err));
      setState("error");
    }
  };

  const buttonLabel =
    label ?? (hasToken ? "MFA token получен ✓" : "Получить MFA token (acr=2)");

  return (
    <div className="space-y-1">
      <button
        type="button"
        onClick={() => void handleClick()}
        disabled={state === "requesting"}
        className={`rounded border px-3 py-1.5 text-xs font-medium ${
          hasToken
            ? "border-green-300 bg-green-50 text-green-900 hover:bg-green-100"
            : "border-brand bg-brand-soft text-brand-strong hover:bg-brand/20"
        } disabled:opacity-50`}
      >
        {state === "requesting" ? "Открываем Keycloak…" : buttonLabel}
      </button>
      {error && (
        <p role="alert" className="text-xs text-red-700">
          {error}
        </p>
      )}
      {state !== "requesting" && hasToken && (
        <p className="text-xs text-gray-500">
          Token действителен ограниченное время (Keycloak session). При
          истечении нажмите кнопку ещё раз.
        </p>
      )}
    </div>
  );
}
