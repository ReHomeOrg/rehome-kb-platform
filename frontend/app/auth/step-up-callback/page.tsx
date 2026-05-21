"use client";

/**
 * Step-up MFA callback page (ADR-0019 §«MFA»).
 *
 * Opened как popup от parent (admin UI initiating MFA-protected action).
 * Keycloak redirects here с URL fragment containing:
 *   #access_token=...&id_token=...&state=...&token_type=Bearer&expires_in=...
 *
 * This page extracts the tokens, posts message back to opener, и closes
 * itself. Если page открыта напрямую (без opener), показывает helpful error.
 */

import { useEffect, useState } from "react";

import { postStepUpCallbackMessage } from "@/lib/auth/step-up";

export default function StepUpCallbackPage(): JSX.Element {
  const [orphan, setOrphan] = useState(false);

  useEffect(() => {
    if (!window.opener) {
      setOrphan(true);
      return;
    }
    postStepUpCallbackMessage();
    // Give opener a tick to process сообщение, then close.
    const timer = setTimeout(() => {
      try {
        window.close();
      } catch {
        // ignore
      }
    }, 250);
    return () => clearTimeout(timer);
  }, []);

  return (
    <main className="mx-auto max-w-md p-8 text-center">
      {orphan ? (
        <>
          <h1 className="text-lg font-semibold">Step-up callback</h1>
          <p className="mt-2 text-sm text-gray-600">
            Эта страница работает как popup callback. Если вы открыли её
            напрямую — закройте окно и инициируйте step-up через admin UI.
          </p>
        </>
      ) : (
        <>
          <h1 className="text-lg font-semibold">Авторизация завершена</h1>
          <p className="mt-2 text-sm text-gray-600">
            Возвращаемся в admin UI…
          </p>
        </>
      )}
    </main>
  );
}
