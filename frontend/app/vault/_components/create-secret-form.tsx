"use client";

/**
 * Create secret form (ADR-0016 Slice 2, personal-only).
 *
 * Flow:
 * 1. Generate per-secret AES key.
 * 2. Encrypt title (separate blob) и payload (separate blob) под secret key.
 * 3. Wrap secret key под vaultKey → self-wrap.
 * 4. POST /vault/secrets с {title_ciphertext, blob_ciphertext, wraps:[self]}.
 *
 * Self-wrap для personal use — единственный wrap (group sharing — Slice 3).
 */

import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import { createVaultSecret } from "@/lib/api/vault";
import {
  encryptBlob,
  generateSecretKey,
  toBase64,
  wrapSecretKeyForUser,
} from "@/lib/vault/crypto";
import { getVaultKey } from "@/lib/vault/session";

interface Props {
  userId: string;
  onCancel: () => void;
  onSuccess: () => void;
}

const CATEGORIES = [
  "password",
  "ssh-key",
  "api-key",
  "bank",
  "kep-token",
  "other",
];

export default function CreateSecretForm({
  userId,
  onCancel,
  onSuccess,
}: Props): JSX.Element {
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("password");
  const [payload, setPayload] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    setError(null);
    if (!title.trim()) {
      setError("Title не может быть пустым");
      return;
    }
    if (!payload) {
      setError("Содержимое не может быть пустым");
      return;
    }
    const vaultKey = getVaultKey();
    if (!vaultKey) {
      setError("Vault locked — обновите страницу и разблокируйте");
      return;
    }

    setPending(true);
    try {
      const secretKey = await generateSecretKey();
      const titleBlob = await encryptBlob(secretKey, title.trim());
      const payloadBlob = await encryptBlob(secretKey, payload);
      const wrappedKey = await wrapSecretKeyForUser(vaultKey, secretKey);

      await createVaultSecret({
        title_ciphertext_b64: toBase64(titleBlob),
        category,
        blob_ciphertext_b64: toBase64(payloadBlob),
        wraps: [{ user_id: userId, wrapped_key_b64: toBase64(wrappedKey) }],
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
      });
      onSuccess();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(`${err.status}: ${err.message}`);
      } else {
        setError(err instanceof Error ? err.message : "Ошибка");
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <form
      onSubmit={onSubmit}
      className="flex flex-col gap-3 rounded-md border border-gray-200 bg-gray-50 p-4"
    >
      <h3 className="text-sm font-medium text-gray-700">Новый секрет</h3>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">
            Title <span className="text-red-700">*</span>
          </span>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={200}
            required
            placeholder="Production database"
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Категория</span>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          >
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-gray-700">
          Содержимое <span className="text-red-700">*</span>{" "}
          <span className="text-xs text-gray-500">
            (любой текст: пароль, ключ, JSON, etc.)
          </span>
        </span>
        <textarea
          value={payload}
          onChange={(e) => setPayload(e.target.value)}
          rows={6}
          required
          className="rounded-md border border-gray-300 px-3 py-1.5 font-mono text-xs"
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-gray-700">
          Истекает <span className="text-xs text-gray-500">(опционально)</span>
        </span>
        <input
          type="datetime-local"
          value={expiresAt}
          onChange={(e) => setExpiresAt(e.target.value)}
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
        />
      </label>

      {error ? (
        <p
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-2 text-xs text-red-700"
        >
          {error}
        </p>
      ) : null}

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={pending}
          className="rounded-md bg-gray-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-50"
        >
          {pending ? "Шифруем и сохраняем…" : "Создать"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={pending}
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
        >
          Отмена
        </button>
      </div>
    </form>
  );
}
