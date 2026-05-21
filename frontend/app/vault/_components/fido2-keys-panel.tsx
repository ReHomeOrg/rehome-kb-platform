"use client";

/**
 * FIDO2 keys management panel (ADR-0022 A).
 *
 * - Lists user's registered keys (GET /vault/fido2/credentials).
 * - Allows registering new keys via Fido2RegisterForm (up to MAX_KEYS_PER_USER=5).
 * - Allows revoking individual keys (DELETE /vault/fido2/credentials/{id}).
 */

import { useEffect, useState } from "react";

import {
  FIDO2CredentialView,
  deleteFido2Credential,
  listFido2Credentials,
} from "@/lib/api/vault";
import { ApiError } from "@/lib/api/client";

import Fido2RegisterForm from "./fido2-register-form";

// Configurable cap — must mirror backend `Settings.vault_fido2_max_keys_per_user`
// (#339). Backend enforces authoritative limit via 409; frontend hints UX.
// Defensive fallback: parseInt("abc") = NaN → silently disables UI cap;
// Number.isFinite-guard returns to default 5 so cap displays correctly.
function _parseMaxKeys(): number {
  const parsed = parseInt(process.env.NEXT_PUBLIC_VAULT_MAX_FIDO2_KEYS ?? "5", 10);
  return Number.isFinite(parsed) && parsed >= 1 ? parsed : 5;
}
const MAX_KEYS = _parseMaxKeys();

function describeError(err: unknown): string {
  if (err instanceof ApiError) return `${err.status}: ${err.message}`;
  return err instanceof Error ? err.message : "Ошибка";
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("ru-RU");
  } catch {
    return iso;
  }
}

export default function Fido2KeysPanel(): JSX.Element {
  const [keys, setKeys] = useState<FIDO2CredentialView[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [busyDeleteId, setBusyDeleteId] = useState<string | null>(null);

  const refresh = async (): Promise<void> => {
    try {
      const resp = await listFido2Credentials();
      setKeys(resp.data);
      setError(null);
    } catch (err) {
      setError(describeError(err));
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const handleAddSuccess = (cred: FIDO2CredentialView): void => {
    setKeys((prev) => (prev ? [...prev, cred] : [cred]));
    setAdding(false);
  };

  const handleRevoke = async (id: string, label: string): Promise<void> => {
    const confirmed = window.confirm(
      `Удалить FIDO2 ключ «${label}»? После удаления unlock через этот ключ невозможен.`,
    );
    if (!confirmed) return;
    setBusyDeleteId(id);
    setError(null);
    try {
      await deleteFido2Credential(id);
      setKeys((prev) => (prev ? prev.filter((k) => k.id !== id) : null));
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusyDeleteId(null);
    }
  };

  const atCap = (keys?.length ?? 0) >= MAX_KEYS;

  return (
    <section className="space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">FIDO2 ключи</h2>
          <p className="text-sm text-gray-600">
            Phishing-resistant 2FA вместо TOTP. Зарегистрируйте YubiKey,
            Touch ID, Windows Hello или Passkey. Максимум {MAX_KEYS}{" "}
            ключей на пользователя.
          </p>
        </div>
        {!adding && !atCap && (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            Добавить ключ
          </button>
        )}
      </header>

      {error && (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-900">
          {error}
        </div>
      )}

      {adding && (
        <Fido2RegisterForm onSuccess={handleAddSuccess} onCancel={() => setAdding(false)} />
      )}

      {keys === null ? (
        <p className="text-sm text-gray-500">Загрузка…</p>
      ) : keys.length === 0 ? (
        <p className="text-sm text-gray-500">
          Пока нет зарегистрированных ключей. TOTP grandfathered, но FIDO2
          сильнее (phishing-resistant) — рекомендуем добавить.
        </p>
      ) : (
        <ul className="divide-y divide-gray-200 rounded border border-gray-200 bg-white">
          {keys.map((k) => {
            const label = k.nickname || `Ключ ${k.id.slice(0, 8)}`;
            return (
              <li key={k.id} className="flex items-center justify-between gap-4 p-4">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{label}</p>
                  <p className="text-xs text-gray-500">
                    Добавлен: {formatDate(k.created_at)} • Последнее
                    использование: {formatDate(k.last_used_at)}
                  </p>
                  {k.transports.length > 0 && (
                    <p className="mt-1 text-xs text-gray-500">
                      Transports: {k.transports.join(", ")}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => void handleRevoke(k.id, label)}
                  disabled={busyDeleteId === k.id}
                  className="rounded border border-red-300 px-3 py-1 text-sm text-red-700 hover:bg-red-50 disabled:opacity-50"
                >
                  {busyDeleteId === k.id ? "Удаление…" : "Удалить"}
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {atCap && !adding && (
        <p className="text-xs text-gray-500">
          Достигнут лимит ({MAX_KEYS} ключей). Удалите ненужный ключ
          чтобы зарегистрировать новый.
        </p>
      )}
    </section>
  );
}
