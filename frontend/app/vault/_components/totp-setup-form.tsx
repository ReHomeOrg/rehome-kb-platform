"use client";

/**
 * TOTP 2FA setup wizard (ADR-0016 Slice 4).
 *
 * Flow:
 * 1. Generate fresh TOTP secret локально.
 * 2. Display base32 secret + otpauth URI (manual entry / scan).
 * 3. User вводит 6-digit code из authenticator app.
 * 4. Verify code локально (proof that user actually scanned).
 * 5. Encrypt secret под vaultKey → POST /vault/totp/setup.
 *
 * Zero-knowledge: backend хранит opaque ciphertext, не decrypt'ит.
 * Verification на unlock — тоже clientside (decrypt + compute + compare).
 */

import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api/client";
import { setupTotp } from "@/lib/api/vault";
import { encryptBlob, toBase64 } from "@/lib/vault/crypto";
import { getVaultKey } from "@/lib/vault/session";
import {
  base32Encode,
  generateTotpSecret,
  otpauthQrDataUrl,
  otpauthUri,
  verifyTotpCode,
} from "@/lib/vault/totp";

interface Props {
  /** Label для otpauth URI (e.g. user email или username). */
  accountLabel: string;
  onCancel: () => void;
  onSuccess: () => void;
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    return `${err.status}: ${err.message}`;
  }
  return err instanceof Error ? err.message : "Ошибка";
}

export default function TotpSetupForm({
  accountLabel,
  onCancel,
  onSuccess,
}: Props): JSX.Element {
  const [secret, setSecret] = useState<Uint8Array | null>(null);
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Generate один раз — re-mount cycle получит новый secret.
    setSecret(generateTotpSecret());
  }, []);

  useEffect(() => {
    if (secret === null) return;
    let cancelled = false;
    const uri = otpauthUri(secret, accountLabel, "reHome Vault");
    otpauthQrDataUrl(uri)
      .then((dataUrl) => {
        if (!cancelled) setQrDataUrl(dataUrl);
      })
      .catch(() => {
        // QR render fail — UI silently falls back to plain URI ниже.
        if (!cancelled) setQrDataUrl(null);
      });
    return () => {
      cancelled = true;
    };
  }, [secret, accountLabel]);

  async function onSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    if (!secret) return;
    setError(null);

    if (!/^\d{6}$/.test(code.replace(/\s/g, ""))) {
      setError("Введите 6 цифр из приложения-аутентификатора");
      return;
    }

    const ok = await verifyTotpCode(secret, code);
    if (!ok) {
      setError(
        "Код не подошёл. Проверьте время на устройстве и попробуйте новый код.",
      );
      return;
    }

    const vaultKey = getVaultKey();
    if (!vaultKey) {
      setError("Vault locked — повторите unlock и попробуйте снова.");
      return;
    }

    setPending(true);
    try {
      // Encrypt secret bytes под vaultKey + ship to server.
      const secretText = toBase64(secret);
      const encrypted = await encryptBlob(vaultKey, secretText);
      await setupTotp({ totp_secret_encrypted_b64: toBase64(encrypted) });
      onSuccess();
    } catch (err) {
      setError(describeError(err));
    } finally {
      setPending(false);
    }
  }

  if (secret === null) {
    return <p className="text-xs text-gray-600">Готовим…</p>;
  }

  const secretBase32 = base32Encode(secret);
  const uri = otpauthUri(secret, accountLabel, "reHome Vault");

  return (
    <form
      onSubmit={onSubmit}
      className="flex flex-col gap-3 rounded-md border border-indigo-200 bg-indigo-50/30 p-4"
    >
      <header className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium text-indigo-900">
            Подключение TOTP 2FA
          </h3>
          <p className="mt-1 text-xs text-indigo-900">
            Добавьте секрет в приложение-аутентификатор (Google Authenticator,
            Aegis, Yandex Key и др.) — либо сканированием URI, либо вручную.
            После добавления введите 6-значный код для проверки.
          </p>
        </div>
        <button
          type="button"
          onClick={onCancel}
          disabled={pending}
          className="text-xs text-indigo-900 underline hover:no-underline disabled:opacity-50"
        >
          Отмена
        </button>
      </header>

      <div className="flex flex-col gap-2 rounded-md bg-white p-3 text-xs">
        {qrDataUrl ? (
          <div className="flex flex-col items-center gap-1">
            {/*
              next/image не подходит для inline data: URL — нет remote
              optimisation, fixed 132×132, нет сетевого хита.
            */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={qrDataUrl}
              alt="QR-код для otpauth URI"
              width={132}
              height={132}
              data-testid="totp-qr"
              className="rounded border border-gray-200 bg-white"
            />
            <span className="text-[10px] text-gray-500">
              Отсканируйте в приложении-аутентификаторе.
            </span>
          </div>
        ) : null}
        <label className="flex flex-col gap-1">
          <span className="font-medium text-gray-700">
            Секрет (base32, ручной ввод)
          </span>
          <code
            data-testid="totp-secret"
            className="break-all rounded bg-gray-100 px-2 py-1 font-mono"
          >
            {secretBase32}
          </code>
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-medium text-gray-700">
            otpauth URI (для сканирования вручную)
          </span>
          <code
            data-testid="totp-uri"
            className="break-all rounded bg-gray-100 px-2 py-1 font-mono text-[10px]"
          >
            {uri}
          </code>
        </label>
      </div>

      <label className="flex flex-col gap-1 text-xs">
        <span className="font-medium">
          Код из приложения <span className="text-red-700">*</span>
        </span>
        <input
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          maxLength={9}
          required
          placeholder="123 456"
          className="rounded-md border border-gray-300 px-3 py-1.5 font-mono"
        />
      </label>

      {error ? (
        <p
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 px-2 py-1 text-xs text-red-700"
        >
          {error}
        </p>
      ) : null}

      <button
        type="submit"
        disabled={pending}
        className="self-start rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800 disabled:opacity-50"
      >
        {pending ? "Включаем…" : "Подключить 2FA"}
      </button>
    </form>
  );
}
