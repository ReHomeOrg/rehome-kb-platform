"use client";

/**
 * Single secret detail view (ADR-0016 Slice 2).
 *
 * - Decrypts blob client-side, displays plaintext с copy-to-clipboard.
 * - Edit toggles textarea + PUT с expected_version (optimistic concurrency).
 * - Delete confirms + DELETE; redirect /vault.
 *
 * Each detail-fetch писывается в audit_log на backend (PZ §8). Это OK,
 * frontend никаких локальных audit'ов не пишет.
 */

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  deleteVaultSecret,
  getVaultSecret,
  updateVaultSecret,
  type VaultSecretView,
} from "@/lib/api/vault";
import {
  decryptBlob,
  encryptBlob,
  fromBase64,
  toBase64,
  unwrapSecretKeyForUser,
} from "@/lib/vault/crypto";
import { getVaultKey } from "@/lib/vault/session";

interface DecryptedSecret {
  raw: VaultSecretView;
  secretKey: CryptoKey;
  title: string;
  payload: string;
}

interface Props {
  secretId: string;
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    return `${err.status}: ${err.message}`;
  }
  return err instanceof Error ? err.message : "Ошибка";
}

export default function SecretDetail({ secretId }: Props): JSX.Element {
  const router = useRouter();
  const [state, setState] = useState<DecryptedSecret | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [editing, setEditing] = useState(false);
  const [editedPayload, setEditedPayload] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const [deleting, setDeleting] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);

  const [copyStatus, setCopyStatus] = useState<string | null>(null);

  async function load(): Promise<void> {
    setLoading(true);
    setError(null);
    const vaultKey = getVaultKey();
    if (!vaultKey) {
      setError("Vault locked — повторите unlock");
      setLoading(false);
      return;
    }
    try {
      const detail = await getVaultSecret(secretId);
      const wrappedKey = fromBase64(detail.wrapped_key_b64);
      const secretKey = await unwrapSecretKeyForUser(vaultKey, wrappedKey);
      const title = await decryptBlob(
        secretKey,
        fromBase64(detail.title_ciphertext_b64),
      );
      const payload = await decryptBlob(
        secretKey,
        fromBase64(detail.blob_ciphertext_b64),
      );
      setState({ raw: detail, secretKey, title, payload });
      setEditedPayload(payload);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [secretId]);

  async function onSave(): Promise<void> {
    if (!state || saving) return;
    setSaveError(null);
    setSaving(true);
    try {
      const newBlob = await encryptBlob(state.secretKey, editedPayload);
      await updateVaultSecret(state.raw.id, {
        blob_ciphertext_b64: toBase64(newBlob),
        expected_version: state.raw.payload_version,
      });
      setEditing(false);
      await load();
    } catch (err) {
      setSaveError(describeError(err));
    } finally {
      setSaving(false);
    }
  }

  async function onDelete(): Promise<void> {
    if (!state || deleting) return;
    setDeleting(true);
    try {
      await deleteVaultSecret(state.raw.id);
      router.push("/vault");
      router.refresh();
    } catch (err) {
      setError(describeError(err));
      setDeleting(false);
    }
  }

  async function onCopy(): Promise<void> {
    if (!state) return;
    try {
      await navigator.clipboard.writeText(state.payload);
      setCopyStatus("Скопировано");
      setTimeout(() => setCopyStatus(null), 2000);
    } catch {
      setCopyStatus("Не удалось скопировать");
      setTimeout(() => setCopyStatus(null), 3000);
    }
  }

  if (loading) {
    return <p className="text-sm text-gray-500">Расшифровываем…</p>;
  }
  if (error || !state) {
    return (
      <p
        role="alert"
        className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700"
      >
        {error ?? "Ошибка"}
      </p>
    );
  }

  return (
    <section className="flex flex-col gap-4">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-gray-900">{state.title}</h2>
          <p className="mt-1 text-xs text-gray-500">
            {state.raw.category} · версия {state.raw.payload_version} ·
            обновлено{" "}
            {new Date(state.raw.updated_at).toLocaleString("ru-RU")}
            {state.raw.expires_at
              ? ` · истекает ${new Date(state.raw.expires_at).toLocaleDateString("ru-RU")}`
              : ""}
          </p>
        </div>
      </header>

      {editing ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void onSave();
          }}
          className="flex flex-col gap-2"
        >
          <textarea
            value={editedPayload}
            onChange={(e) => setEditedPayload(e.target.value)}
            rows={8}
            className="rounded-md border border-gray-300 px-3 py-2 font-mono text-xs"
          />
          {saveError ? (
            <p
              role="alert"
              className="rounded-md border border-red-200 bg-red-50 p-2 text-xs text-red-700"
            >
              {saveError}
            </p>
          ) : null}
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={saving}
              className="rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800 disabled:opacity-50"
            >
              {saving ? "Сохраняем…" : "Сохранить"}
            </button>
            <button
              type="button"
              onClick={() => {
                setEditing(false);
                setEditedPayload(state.payload);
                setSaveError(null);
              }}
              disabled={saving}
              className="rounded-md border border-gray-300 px-3 py-1.5 text-xs hover:bg-gray-50"
            >
              Отмена
            </button>
          </div>
        </form>
      ) : (
        <section className="flex flex-col gap-2">
          <pre className="overflow-x-auto rounded-md border border-gray-200 bg-gray-50 p-3 font-mono text-xs">
            {state.payload}
          </pre>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void onCopy()}
              className="rounded-md border border-gray-300 px-3 py-1.5 text-xs hover:bg-gray-50"
            >
              Скопировать
            </button>
            <button
              type="button"
              onClick={() => setEditing(true)}
              className="rounded-md border border-gray-300 px-3 py-1.5 text-xs hover:bg-gray-50"
            >
              Редактировать
            </button>
            {!deleteConfirm ? (
              <button
                type="button"
                onClick={() => setDeleteConfirm(true)}
                className="rounded-md border border-red-300 bg-red-50 px-3 py-1.5 text-xs font-medium text-red-800 hover:bg-red-100"
              >
                Удалить
              </button>
            ) : null}
            {copyStatus ? (
              <span className="text-xs text-green-700">{copyStatus}</span>
            ) : null}
          </div>
          {deleteConfirm ? (
            <div className="flex flex-col gap-2 rounded-md border border-red-200 bg-red-50/40 p-3">
              <p className="text-xs text-red-900">
                Soft-delete. Записи vault&apos;а хранятся для compliance, но
                становятся недоступны.
              </p>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => void onDelete()}
                  disabled={deleting}
                  className="rounded-md bg-red-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-800 disabled:opacity-50"
                >
                  {deleting ? "Удаляем…" : "Подтвердить"}
                </button>
                <button
                  type="button"
                  onClick={() => setDeleteConfirm(false)}
                  disabled={deleting}
                  className="rounded-md border border-gray-300 px-3 py-1.5 text-xs hover:bg-gray-50"
                >
                  Отмена
                </button>
              </div>
            </div>
          ) : null}
        </section>
      )}
    </section>
  );
}
