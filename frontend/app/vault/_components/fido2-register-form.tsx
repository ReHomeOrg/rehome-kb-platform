"use client";

/**
 * FIDO2 registration ceremony (ADR-0022 A).
 *
 * Flow:
 * 1. User clicks «Add FIDO2 key» → enters optional nickname.
 * 2. POST /vault/fido2/register-begin → options (challenge, exclude, user).
 * 3. `navigator.credentials.create({publicKey: options})` → authenticator
 *    prompts user (YubiKey button / Touch ID / Windows Hello).
 * 4. POST /vault/fido2/register-complete → backend verifies attestation +
 *    persists credential row.
 * 5. UI confirms «Key added» + refreshes list.
 */

import { useState } from "react";

import {
  FIDO2CredentialView,
  fido2RegisterBegin,
  fido2RegisterComplete,
} from "@/lib/api/vault";
import { ApiError } from "@/lib/api/client";
import {
  decodeCreationOptions,
  encodeRegistrationCredential,
  isWebAuthnSupported,
} from "@/lib/vault/webauthn";

interface Props {
  onSuccess: (credential: FIDO2CredentialView) => void;
  onCancel: () => void;
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 409) return "Достигнут лимит ключей (макс. 5). Удалите ненужный ключ.";
    return `${err.status}: ${err.message}`;
  }
  if (err instanceof DOMException) {
    if (err.name === "NotAllowedError") {
      return "Регистрация отменена или истекло время ожидания authenticator'а.";
    }
    if (err.name === "InvalidStateError") {
      return "Этот ключ уже зарегистрирован.";
    }
    return `${err.name}: ${err.message}`;
  }
  return err instanceof Error ? err.message : "Ошибка";
}

export default function Fido2RegisterForm({ onSuccess, onCancel }: Props): JSX.Element {
  const [nickname, setNickname] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isWebAuthnSupported()) {
    return (
      <div className="rounded border border-yellow-200 bg-yellow-50 p-4 text-sm text-yellow-900">
        Браузер не поддерживает WebAuthn (FIDO2). Используйте Chromium /
        Firefox / Safari актуальной версии.
        <div className="mt-3">
          <button
            type="button"
            onClick={onCancel}
            className="rounded border border-yellow-300 px-3 py-1 text-yellow-900 hover:bg-yellow-100"
          >
            Закрыть
          </button>
        </div>
      </div>
    );
  }

  const handleSubmit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const { options } = await fido2RegisterBegin(displayName || undefined);
      const creationOptions = decodeCreationOptions(options);
      const credential = (await navigator.credentials.create({
        publicKey: creationOptions,
      })) as PublicKeyCredential | null;
      if (!credential) {
        throw new Error("Authenticator не вернул credential");
      }
      const created = await fido2RegisterComplete({
        credential: encodeRegistrationCredential(credential),
        nickname: nickname || null,
      });
      onSuccess(created);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-4 rounded border border-gray-200 bg-white p-4"
    >
      <h3 className="text-lg font-semibold">Добавить FIDO2 ключ</h3>
      <p className="text-sm text-gray-600">
        Нажмите «Зарегистрировать» — браузер запросит подключенный
        authenticator (YubiKey / Touch ID / Windows Hello / Passkey).
      </p>

      <label className="block">
        <span className="text-sm font-medium">Название ключа (опционально)</span>
        <input
          type="text"
          maxLength={100}
          value={nickname}
          onChange={(e) => setNickname(e.target.value)}
          placeholder="напр. YubiKey 5C primary"
          className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm"
          disabled={busy}
        />
      </label>

      <label className="block">
        <span className="text-sm font-medium">Отображаемое имя (опционально)</span>
        <input
          type="text"
          maxLength={100}
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          placeholder="Используется в диалоге authenticator'а"
          className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm"
          disabled={busy}
        />
      </label>

      {error && (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-900">
          {error}
        </div>
      )}

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={busy}
          className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {busy ? "Регистрация..." : "Зарегистрировать"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="rounded border border-gray-300 px-4 py-2 text-sm font-medium hover:bg-gray-50 disabled:opacity-50"
        >
          Отмена
        </button>
      </div>
    </form>
  );
}
