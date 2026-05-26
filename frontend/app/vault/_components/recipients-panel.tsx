"use client";

/**
 * Recipients panel (ADR-0017 §E true revoke, 2026-05-27).
 *
 * Flow:
 * 1. Mount: fetch текущий список recipients (GET /wraps).
 * 2. Owner видит каждого recipient'а с кнопкой «Отозвать».
 * 3. Revoke click → rotation flow:
 *    a. Filter target user'а из surviving recipients.
 *    b. Generate new secret_key (32 random bytes; AES-256-GCM CryptoKey).
 *    c. Re-encrypt title + blob с новым secret_key.
 *    d. Для каждого survivor'а: getUserPubkey + wrapSecretKeyForGroup.
 *    e. POST /rotate с {new_title, new_blob, expected_version, new_wraps[]}.
 * 4. После success — onRotated callback с обновлённым view (parent reload'нёт
 *    и обновит state.secretKey + payload_version).
 *
 * Owner всегда включается в new_wraps (даже если он revoke'ит других —
 * сам себе доступ сохраняет). Edge case revoke-self — separate archive flow.
 */

import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  getUserPubkey,
  listSecretWraps,
  rotateVaultSecret,
  type VaultSecretView,
  type VaultSecretWrapView,
} from "@/lib/api/vault";
import {
  encryptBlob,
  fromBase64,
  generateSecretKey,
  toBase64,
  wrapSecretKeyForGroup,
  wrapSecretKeyForUser,
} from "@/lib/vault/crypto";
import { getVaultKey } from "@/lib/vault/session";

interface Props {
  secretId: string;
  ownerId: string;
  /** Current decrypted plaintext title — re-encrypt'ится новым secret_key. */
  plaintextTitle: string;
  /** Current decrypted plaintext payload — re-encrypt'ится новым secret_key. */
  plaintextPayload: string;
  currentVersion: number;
  onCancel: () => void;
  onRotated: (updated: VaultSecretView) => void;
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { detail?: unknown } | null;
    if (typeof body?.detail === "string") {
      return `${err.status}: ${body.detail}`;
    }
    return `${err.status}: ${err.message}`;
  }
  return err instanceof Error ? err.message : "Ошибка";
}

export default function RecipientsPanel({
  secretId,
  ownerId,
  plaintextTitle,
  plaintextPayload,
  currentVersion,
  onCancel,
  onRotated,
}: Props): JSX.Element {
  const [recipients, setRecipients] = useState<VaultSecretWrapView[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [progress, setProgress] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load(): Promise<void> {
      setLoading(true);
      setError(null);
      try {
        const resp = await listSecretWraps(secretId);
        if (!cancelled) setRecipients(resp.data);
      } catch (err) {
        if (!cancelled) setError(describeError(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [secretId]);

  async function onRevoke(targetUserId: string): Promise<void> {
    if (revoking) return;
    const vaultKey = getVaultKey();
    if (!vaultKey) {
      setError("Vault locked — повторите unlock");
      return;
    }
    setRevoking(targetUserId);
    setError(null);
    setProgress(null);

    try {
      // 1. Survivors = recipients - target (owner всегда уже в списке).
      const survivors = recipients.filter((r) => r.user_id !== targetUserId);

      // 2. Generate new secret_key + re-encrypt title + blob.
      setProgress("Генерируем новый ключ…");
      const newSecretKey = await generateSecretKey();
      const newTitleCt = await encryptBlob(newSecretKey, plaintextTitle);
      const newBlobCt = await encryptBlob(newSecretKey, plaintextPayload);

      // 3. Wrap newSecretKey для каждого survivor'а. Owner получает wrap
      // через vaultKey (wrapSecretKeyForUser); остальные — через X25519
      // sealed-box (wrapSecretKeyForGroup) под их pubkey.
      setProgress("Готовим wraps…");
      const newWraps: {
        user_id: string;
        group_id?: string | null;
        wrapped_key_b64: string;
      }[] = [];

      // Owner: использует свой vaultKey для self-wrap. Это устойчивый
      // pattern из create-secret-form.tsx.
      const ownerWrapped = await wrapSecretKeyForUser(vaultKey, newSecretKey);
      newWraps.push({
        user_id: ownerId,
        group_id: null,
        wrapped_key_b64: toBase64(ownerWrapped),
      });

      // Остальные survivors через X25519 (исключая owner'а — он уже добавлен).
      const externalSurvivors = survivors.filter((s) => s.user_id !== ownerId);
      for (let i = 0; i < externalSurvivors.length; i++) {
        const r = externalSurvivors[i]!;
        setProgress(
          `Шифруем для ${i + 1}/${externalSurvivors.length}: ${r.user_id.slice(0, 8)}…`,
        );
        const pkResp = await getUserPubkey(r.user_id);
        const pubkey = fromBase64(pkResp.x25519_pubkey_b64);
        const wrapped = await wrapSecretKeyForGroup(pubkey, newSecretKey);
        newWraps.push({
          user_id: r.user_id,
          group_id: r.group_id,
          wrapped_key_b64: toBase64(wrapped),
        });
      }

      // 4. POST /rotate.
      setProgress("Применяем rotation…");
      const updated = await rotateVaultSecret(secretId, {
        new_title_ciphertext_b64: toBase64(newTitleCt),
        new_blob_ciphertext_b64: toBase64(newBlobCt),
        expected_version: currentVersion,
        new_wraps: newWraps,
      });

      onRotated(updated);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setRevoking(null);
      setProgress(null);
    }
  }

  return (
    <section className="flex flex-col gap-3 rounded-md border border-orange-200 bg-orange-50/40 p-3">
      <header className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-orange-900">
          Получатели доступа
        </h3>
        <button
          type="button"
          onClick={onCancel}
          disabled={revoking !== null}
          className="text-xs text-orange-900 underline hover:no-underline disabled:opacity-50"
        >
          Закрыть
        </button>
      </header>

      <p className="text-xs text-orange-900">
        Отзыв доступа выполняет <strong>ротацию ключа</strong>: генерируется
        новый секретный ключ, blob и title перешифровываются, для оставшихся
        получателей создаются новые wraps. Кэшированные plaintext&apos;ы у
        отозванного пользователя становятся бесполезны (ADR-0017 §E).
      </p>

      {loading ? (
        <p className="text-xs text-gray-600">Загружаем получателей…</p>
      ) : recipients.length === 0 ? (
        <p className="text-xs text-gray-600">
          Никому не расшарено (только вы — owner).
        </p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {recipients.map((r) => {
            const isOwner = r.user_id === ownerId;
            return (
              <li
                key={r.user_id + (r.group_id ?? "")}
                className="flex items-center justify-between rounded-md border border-orange-100 bg-white px-2 py-1.5 text-xs"
              >
                <span className="flex flex-col">
                  <code className="font-mono">{r.user_id}</code>
                  {r.group_id ? (
                    <span className="text-gray-600">
                      через группу:{" "}
                      <code className="font-mono">{r.group_id.slice(0, 8)}…</code>
                    </span>
                  ) : null}
                </span>
                {isOwner ? (
                  <span className="text-gray-500">(вы — owner)</span>
                ) : (
                  <button
                    type="button"
                    onClick={() => void onRevoke(r.user_id)}
                    disabled={revoking !== null}
                    className="rounded-md border border-red-300 bg-red-50 px-2 py-1 text-xs font-medium text-red-800 hover:bg-red-100 disabled:opacity-50"
                  >
                    {revoking === r.user_id ? "Отзываем…" : "Отозвать"}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {progress ? (
        <p className="rounded-md border border-orange-200 bg-orange-50 px-2 py-1 text-xs text-orange-900">
          {progress}
        </p>
      ) : null}

      {error ? (
        <p
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 px-2 py-1 text-xs text-red-700"
        >
          {error}
        </p>
      ) : null}
    </section>
  );
}
