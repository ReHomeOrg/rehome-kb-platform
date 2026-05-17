"use client";

/**
 * Share-with-group panel (ADR-0017 §E, Slice 3.5).
 *
 * Flow:
 * 1. Owner выбирает группу из своих vault-групп.
 * 2. Client fetches members группы.
 * 3. Для каждого member (кроме owner'а себя — уже имеет wrap):
 *    - Fetch user pubkey.
 *    - Wrap recovered secretKey под user.pubkey (X25519 sealed-box).
 * 4. POST batch wraps на `/vault/secrets/{id}/wraps` с group_id lineage.
 *
 * Caveat (ADR-0017 §E «Remove member» comment): revoke не делает старые
 * secret_keys forgotten. Это применимо и здесь — added members могут
 * cache decrypted key и сохранять access даже после revoke. Stage 2 —
 * true rotate flow.
 */

import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  addSecretWraps,
  getUserPubkey,
  listGroupMembers,
  listVaultGroups,
  type VaultGroupView,
} from "@/lib/api/vault";
import { toBase64, wrapSecretKeyForGroup, fromBase64 } from "@/lib/vault/crypto";

interface Props {
  secretId: string;
  /** Owner's user_id — exclude из re-wrap (он уже имеет wrap). */
  ownerId: string;
  /** Recovered secretKey (extractable AES-GCM) — для re-wrap. */
  secretKey: CryptoKey;
  onCancel: () => void;
  onSuccess: () => void;
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

export default function ShareSecretPanel({
  secretId,
  ownerId,
  secretKey,
  onCancel,
  onSuccess,
}: Props): JSX.Element {
  const [groups, setGroups] = useState<VaultGroupView[]>([]);
  const [loadingGroups, setLoadingGroups] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedGroupId, setSelectedGroupId] = useState<string>("");
  const [sharing, setSharing] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load(): Promise<void> {
      setLoadingGroups(true);
      setError(null);
      try {
        const resp = await listVaultGroups();
        if (!cancelled) setGroups(resp.data);
      } catch (err) {
        if (!cancelled) setError(describeError(err));
      } finally {
        if (!cancelled) setLoadingGroups(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  async function onShare(): Promise<void> {
    if (!selectedGroupId || sharing) return;
    setError(null);
    setSharing(true);
    setProgress(null);
    try {
      // 1. Fetch group members.
      setProgress("Запрашиваем список участников…");
      const membersResp = await listGroupMembers(selectedGroupId);
      const recipients = membersResp.data.filter((m) => m.user_id !== ownerId);
      if (recipients.length === 0) {
        setError(
          "В группе нет других участников помимо вас — некому шарить.",
        );
        setSharing(false);
        return;
      }
      // 2. Iterate: pubkey lookup → wrap → collect.
      const wraps: { user_id: string; group_id: string; wrapped_key_b64: string }[] = [];
      for (let i = 0; i < recipients.length; i++) {
        const m = recipients[i]!;
        setProgress(
          `Шифруем для ${i + 1}/${recipients.length}: ${m.user_id.slice(0, 8)}…`,
        );
        const pkResp = await getUserPubkey(m.user_id);
        const pubkey = fromBase64(pkResp.x25519_pubkey_b64);
        const wrapped = await wrapSecretKeyForGroup(pubkey, secretKey);
        wraps.push({
          user_id: m.user_id,
          group_id: selectedGroupId,
          wrapped_key_b64: toBase64(wrapped),
        });
      }
      // 3. POST batch.
      setProgress("Сохраняем wraps…");
      await addSecretWraps(secretId, { wraps });
      onSuccess();
    } catch (err) {
      setError(describeError(err));
    } finally {
      setSharing(false);
      setProgress(null);
    }
  }

  return (
    <section className="flex flex-col gap-3 rounded-md border border-blue-200 bg-blue-50/40 p-3">
      <header className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-blue-900">
          Поделиться с группой
        </h3>
        <button
          type="button"
          onClick={onCancel}
          disabled={sharing}
          className="text-xs text-blue-900 underline hover:no-underline disabled:opacity-50"
        >
          Закрыть
        </button>
      </header>

      <p className="text-xs text-blue-900">
        Каждому участнику группы будет создан отдельный wrap (X25519
        sealed-box), зашифрованный под его pubkey. Lineage сохраняется
        для последующих re-share / revoke (ADR-0017).
      </p>

      {loadingGroups ? (
        <p className="text-xs text-gray-600">Загружаем группы…</p>
      ) : groups.length === 0 ? (
        <p className="text-xs text-gray-600">
          Вы не состоите ни в одной группе. Создайте группу через таб
          «Группы».
        </p>
      ) : (
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium">Группа</span>
          <select
            value={selectedGroupId}
            onChange={(e) => setSelectedGroupId(e.target.value)}
            disabled={sharing}
            className="rounded-md border border-gray-300 px-2 py-1 text-xs"
          >
            <option value="">— выберите —</option>
            {groups.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </select>
        </label>
      )}

      {progress ? (
        <p className="rounded-md border border-blue-200 bg-blue-50 px-2 py-1 text-xs text-blue-900">
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

      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => void onShare()}
          disabled={sharing || !selectedGroupId}
          className="rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800 disabled:opacity-50"
        >
          {sharing ? "Шифруем…" : "Поделиться"}
        </button>
      </div>
    </section>
  );
}
