"use client";

/**
 * Secrets list (ADR-0016 Slice 2).
 *
 * Backend возвращает metadata + title_ciphertext. Frontend decrypt'ит
 * titles локально через vaultKey-unwrap'ed secret_keys. Каждый секрет
 * требует:
 * 1. GET /vault/secrets/{id} → wrapped_key + blob (full detail).
 * 2. Unwrap key vaultKey'ом → secret_key.
 * 3. Decrypt title_ciphertext.
 *
 * Performance: для list view дёргаем full detail per row только для
 * title decrypt'а. Trade-off acceptable (typical staff vault — десятки
 * секретов, не тысячи). Если станет проблемой — backend backlog:
 * batch-get с title-only response.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  getVaultSecret,
  listVaultSecrets,
  type VaultSecretMetadataView,
} from "@/lib/api/vault";
import {
  decryptBlob,
  fromBase64,
  unwrapSecretKeyForUser,
} from "@/lib/vault/crypto";
import { getVaultKey } from "@/lib/vault/session";

interface DecryptedRow extends VaultSecretMetadataView {
  decryptedTitle: string | null; // null если decrypt'ить не удалось
  decryptError: string | null;
}

interface Props {
  onCreateClick: () => void;
  /** Bump для триггера reload — Slice 2 simple form pattern. */
  reloadToken: number;
}

export default function SecretsList({
  onCreateClick,
  reloadToken,
}: Props): JSX.Element {
  const [rows, setRows] = useState<DecryptedRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const vaultKey = getVaultKey();
    if (!vaultKey) {
      setError("Vault locked — повторите unlock");
      setLoading(false);
      return;
    }

    async function loadAndDecrypt(): Promise<void> {
      setLoading(true);
      setError(null);
      try {
        const list = await listVaultSecrets();
        const decoded: DecryptedRow[] = [];
        for (const meta of list.data) {
          // Per-row full fetch для wrapped_key + title decrypt.
          // Backend audit'ит каждый detail-read — ожидаемое поведение
          // (PZ §7/§8 audit просмотров).
          try {
            const detail = await getVaultSecret(meta.id);
            const wrappedKey = fromBase64(detail.wrapped_key_b64);
            const secretKey = await unwrapSecretKeyForUser(vaultKey!, wrappedKey);
            const titleBytes = fromBase64(detail.title_ciphertext_b64);
            const title = await decryptBlob(secretKey, titleBytes);
            decoded.push({ ...meta, decryptedTitle: title, decryptError: null });
          } catch (e) {
            decoded.push({
              ...meta,
              decryptedTitle: null,
              decryptError:
                e instanceof Error ? e.message : "decrypt failed",
            });
          }
        }
        if (!cancelled) {
          setRows(decoded);
        }
      } catch (e) {
        if (cancelled) return;
        if (e instanceof ApiError) {
          setError(`${e.status}: ${e.message}`);
        } else {
          setError(e instanceof Error ? e.message : "Ошибка загрузки");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void loadAndDecrypt();
    return () => {
      cancelled = true;
    };
  }, [reloadToken]);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-gray-700">Секреты</h3>
        <button
          type="button"
          onClick={onCreateClick}
          className="rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800"
        >
          + Новый секрет
        </button>
      </div>
      {loading ? (
        <p className="text-xs text-gray-500">Загружаем и расшифровываем…</p>
      ) : error ? (
        <p
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-2 text-xs text-red-700"
        >
          {error}
        </p>
      ) : rows.length === 0 ? (
        <p className="text-xs text-gray-500">
          Секретов нет. Создайте первый через «+ Новый секрет».
        </p>
      ) : (
        <ul className="divide-y divide-gray-100 rounded-md border border-gray-200">
          {rows.map((r) => (
            <li
              key={r.id}
              className="flex items-center justify-between gap-3 p-3 text-sm hover:bg-gray-50"
            >
              <div className="min-w-0 flex-1">
                <Link
                  href={`/vault/${encodeURIComponent(r.id)}`}
                  className="block truncate font-medium text-gray-900 hover:underline"
                >
                  {r.decryptedTitle ?? "[ошибка расшифровки]"}
                </Link>
                <p className="text-xs text-gray-500">
                  {r.category} · обновлено{" "}
                  {new Date(r.updated_at).toLocaleDateString("ru-RU")}
                  {r.expires_at ? (
                    <ExpiryHint expiresAt={r.expires_at} />
                  ) : null}
                </p>
                {r.decryptError ? (
                  <p className="mt-1 text-xs text-red-700">
                    decrypt error: {r.decryptError}
                  </p>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const MS_PER_DAY = 24 * 60 * 60 * 1000;

function ExpiryHint({ expiresAt }: { expiresAt: string }): JSX.Element {
  const ms = new Date(expiresAt).getTime();
  const now = Date.now();
  const dateStr = new Date(expiresAt).toLocaleDateString("ru-RU");
  if (Number.isNaN(ms)) {
    return <span> · истекает {dateStr}</span>;
  }
  if (ms < now) {
    return (
      <span
        data-testid="expiry-expired"
        className="text-red-700"
      >
        {" "}· истёк {dateStr}
      </span>
    );
  }
  if (ms - now < 30 * MS_PER_DAY) {
    return (
      <span
        data-testid="expiry-soon"
        className="text-amber-700"
      >
        {" "}· истекает {dateStr}
      </span>
    );
  }
  return <span> · истекает {dateStr}</span>;
}
