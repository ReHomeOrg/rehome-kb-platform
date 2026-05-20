"use client";

/**
 * Setup escrow ceremony (ADR-0021 A).
 *
 * Flow:
 * 1. User re-types master password (для re-derivation extractable KEK).
 * 2. Client generates 32-byte random escrow_key.
 * 3. Client AES-GCM encrypts KEK raw bytes под escrow_key → escrow_wrap.
 * 4. Client splits escrow_key into 2 Shamir shares (base32-encoded).
 * 5. POST escrow_wrap to /vault/setup-escrow.
 * 6. UI displays 2 shares для печати — пользователь confirm'ит каждый
 *    envelope (директор + юрист) перед continue.
 * 7. Wipe sensitive material из memory.
 *
 * Zero-knowledge preserved: backend хранит только opaque escrow_wrap;
 * никогда не видит escrow_key или shares.
 */

import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import { setupEscrow } from "@/lib/api/vault";
import {
  deriveExtractableKek,
  fromBase64,
  randomBytes,
  toBase64,
} from "@/lib/vault/crypto";
import { shareToBase32, splitSecret } from "@/lib/vault/escrow";

interface Props {
  argonSaltB64: string;
  onSuccess: () => void;
  onCancel: () => void;
}

type CeremonyStep = "password" | "print" | "confirm" | "done";

function describeError(err: unknown): string {
  if (err instanceof ApiError) return `${err.status}: ${err.message}`;
  return err instanceof Error ? err.message : "Ошибка";
}

async function buildEscrowWrap(
  kekBytes: Uint8Array,
  escrowKey: Uint8Array,
): Promise<Uint8Array> {
  const iv = randomBytes(12);
  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    escrowKey as BufferSource,
    { name: "AES-GCM", length: 256 },
    /* extractable */ false,
    ["encrypt"],
  );
  const ct = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: iv as BufferSource },
    cryptoKey,
    kekBytes as BufferSource,
  );
  const blob = new Uint8Array(iv.length + ct.byteLength);
  blob.set(iv, 0);
  blob.set(new Uint8Array(ct), iv.length);
  return blob;
}

function chunked(s: string, n: number): string {
  return s.match(new RegExp(`.{1,${n}}`, "g"))?.join(" ") ?? s;
}

export default function SetupEscrowForm({
  argonSaltB64,
  onSuccess,
  onCancel,
}: Props): JSX.Element {
  const [step, setStep] = useState<CeremonyStep>("password");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [shares, setShares] = useState<{ director: string; lawyer: string } | null>(null);
  const [directorAck, setDirectorAck] = useState(false);
  const [lawyerAck, setLawyerAck] = useState(false);

  const handleCeremony = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    if (busy) return;
    setError(null);
    setBusy(true);

    let kekBytes: Uint8Array | null = null;
    let escrowKey: Uint8Array | null = null;
    try {
      const salt = fromBase64(argonSaltB64);
      kekBytes = await deriveExtractableKek(password, salt);
      escrowKey = randomBytes(32);

      const escrowWrap = await buildEscrowWrap(kekBytes, escrowKey);
      const shareBlobs = await splitSecret(escrowKey, { threshold: 2 });
      const director = shareToBase32(shareBlobs[0]);
      const lawyer = shareToBase32(shareBlobs[1]);

      await setupEscrow({ escrow_wrap_b64: toBase64(escrowWrap) });
      setShares({ director, lawyer });
      setStep("print");
    } catch (err) {
      setError(describeError(err));
    } finally {
      // Wipe sensitive material.
      kekBytes?.fill(0);
      escrowKey?.fill(0);
      setPassword("");
      setBusy(false);
    }
  };

  const handleConfirm = (): void => {
    if (!directorAck || !lawyerAck) return;
    // Drop shares from React state — caller обязан напечатать до этого.
    setShares(null);
    setStep("done");
    onSuccess();
  };

  if (step === "password") {
    return (
      <form
        onSubmit={handleCeremony}
        className="space-y-4 rounded border border-gray-200 bg-white p-4"
      >
        <h3 className="text-lg font-semibold">Настроить emergency access</h3>
        <p className="text-sm text-gray-600">
          Подтвердите master password для генерации ceremony shares.
          После этой операции backend сохранит зашифрованный blob, а
          два share&apos;а будут напечатаны для физических envelopes
          (директор + юрист).
        </p>
        <div className="rounded border border-yellow-200 bg-yellow-50 p-3 text-xs text-yellow-900">
          <strong>Внимание:</strong> shares показываются ТОЛЬКО ОДИН раз.
          Сохраните оба envelope&apos;а в физ. сейфах до закрытия страницы.
          Без обоих shares vault станет невосстановимым при потере
          master password.
        </div>
        <label className="block">
          <span className="text-sm font-medium">Master password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="off"
            autoFocus
            className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm"
            disabled={busy}
          />
        </label>
        {error && (
          <div role="alert" className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-900">
            {error}
          </div>
        )}
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={busy || !password}
            className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {busy ? "Генерация..." : "Сгенерировать shares"}
          </button>
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="rounded border border-gray-300 px-4 py-2 text-sm hover:bg-gray-50"
          >
            Отмена
          </button>
        </div>
      </form>
    );
  }

  if (step === "print" && shares) {
    return (
      <div className="space-y-4 rounded border border-gray-200 bg-white p-4">
        <h3 className="text-lg font-semibold">Распечатайте shares</h3>
        <p className="text-sm text-gray-600">
          Два share&apos;а ниже. Каждый — напечатать на отдельный лист,
          положить в sealed envelope + физический сейф. Без ОБОИХ
          shares emergency unlock невозможен.
        </p>

        <section>
          <h4 className="text-sm font-semibold">Share 1 — Директор</h4>
          <p className="text-xs text-gray-500 mb-2">
            Получатель: директор. Сейф: офис.
          </p>
          <pre
            data-testid="share-director"
            className="rounded bg-gray-100 p-3 font-mono text-xs break-all whitespace-pre-wrap"
          >
            {chunked(shares.director, 4)}
          </pre>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={directorAck}
              onChange={(e) => setDirectorAck(e.target.checked)}
              className="mt-1"
            />
            <span>
              Я напечатал share 1, поместил в envelope и передал директору
              для физ. сейфа офиса.
            </span>
          </label>
        </section>

        <section>
          <h4 className="text-sm font-semibold">Share 2 — Юрист</h4>
          <p className="text-xs text-gray-500 mb-2">
            Получатель: юрист (внешняя юр.фирма). Сейф: офис юр.фирмы.
          </p>
          <pre
            data-testid="share-lawyer"
            className="rounded bg-gray-100 p-3 font-mono text-xs break-all whitespace-pre-wrap"
          >
            {chunked(shares.lawyer, 4)}
          </pre>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={lawyerAck}
              onChange={(e) => setLawyerAck(e.target.checked)}
              className="mt-1"
            />
            <span>
              Я напечатал share 2, поместил в envelope и передал юристу
              для физ. сейфа юр.фирмы.
            </span>
          </label>
        </section>

        <div className="rounded border border-red-200 bg-red-50 p-3 text-xs text-red-900">
          После нажатия «Завершить» shares исчезнут из браузера навсегда.
          Убедитесь, что оба напечатаны и confirmed выше.
        </div>

        <button
          type="button"
          onClick={handleConfirm}
          disabled={!directorAck || !lawyerAck}
          className="rounded bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
        >
          Завершить ceremony
        </button>
      </div>
    );
  }

  return <div className="rounded bg-green-50 p-3 text-sm text-green-900">Emergency access настроен.</div>;
}
