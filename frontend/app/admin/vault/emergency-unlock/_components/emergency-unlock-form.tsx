"use client";

/**
 * Emergency unlock ceremony — admin combines 2 shares + decrypts vault
 * client-side (ADR-0021 A).
 *
 * Flow:
 * 1. Admin types target user_id + reason_category + reason_text.
 * 2. Admin pastes 2 base32 shares (from sealed envelopes: директор + юрист).
 * 3. POST /admin/vault/emergency-unlock → backend records event +
 *    returns encrypted key material (escrow_wrap, encrypted_x25519_privkey,
 *    x25519_pubkey, argon_salt) + audit metadata (incident_id, severity,
 *    rkn_notify_required, log_id).
 * 4. Client locally:
 *    - base32ToShare → 2 share blobs
 *    - combineShares → escrow_key (32 bytes)
 *    - AES-GCM decrypt(escrow_wrap, escrow_key) → KEK raw bytes
 *    - AES-GCM decrypt(encrypted_x25519_privkey, KEK) → X25519 privkey
 * 5. Display: audit metadata + recovered material (export buttons).
 *    Wipe escrow_key + KEK + privkey on unmount / explicit lock.
 *
 * Zero-knowledge invariant: backend never sees shares; combine + decrypt
 * never leave admin's browser memory.
 */

import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  EmergencyReasonCategory,
  VaultEmergencyUnlockResponse,
  emergencyUnlock,
} from "@/lib/api/vault";
import { fromBase64 } from "@/lib/vault/crypto";
import { base32ToShare, combineShares } from "@/lib/vault/escrow";

const REASON_LABELS: Record<EmergencyReasonCategory, string> = {
  incident: "Security incident (требует РКН-уведомление)",
  legal_order: "Юридический ордер (РКН / суд)",
  employee_departure: "Увольнение / incapacitation сотрудника",
  forensic_audit: "Forensic audit (ФЗ-152 §17.1)",
  password_lost: "Восстановление master password",
};

interface RecoveredVault {
  kekHex: string;
  privkeyHex: string;
  pubkeyHex: string;
  audit: {
    unlock_log_id: string;
    security_incident_id: string;
    severity: string;
    rkn_notify_required: boolean;
    created_at: string;
  };
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) return `${err.status}: ${err.message}`;
  return err instanceof Error ? err.message : "Ошибка";
}

function toHex(bytes: Uint8Array): string {
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

async function aesGcmDecrypt(blob: Uint8Array, keyBytes: Uint8Array): Promise<Uint8Array> {
  if (blob.length < 12 + 16) {
    throw new Error("blob too short (must be iv + ciphertext + 16-byte tag)");
  }
  const iv = blob.slice(0, 12);
  const ct = blob.slice(12);
  const key = await crypto.subtle.importKey(
    "raw",
    keyBytes as BufferSource,
    { name: "AES-GCM", length: 256 },
    /* extractable */ false,
    ["decrypt"],
  );
  const plain = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: iv as BufferSource },
    key,
    ct as BufferSource,
  );
  return new Uint8Array(plain);
}

export default function EmergencyUnlockForm(): JSX.Element {
  const [targetUserId, setTargetUserId] = useState("");
  const [reason, setReason] = useState<EmergencyReasonCategory>("password_lost");
  const [reasonText, setReasonText] = useState("");
  const [share1, setShare1] = useState("");
  const [share2, setShare2] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recovered, setRecovered] = useState<RecoveredVault | null>(null);

  const handleSubmit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    if (busy) return;
    setError(null);
    setBusy(true);

    let escrowKey: Uint8Array | null = null;
    let kekBytes: Uint8Array | null = null;
    let privkey: Uint8Array | null = null;
    try {
      // 1. Combine shares локально (zero-knowledge invariant).
      const blob1 = base32ToShare(share1);
      const blob2 = base32ToShare(share2);
      escrowKey = await combineShares([blob1, blob2]);
      if (escrowKey.length !== 32) {
        throw new Error(`Unexpected escrow_key length ${escrowKey.length}; expected 32`);
      }

      // 2. POST event + retrieve encrypted material.
      const resp: VaultEmergencyUnlockResponse = await emergencyUnlock({
        target_user_id: targetUserId.trim(),
        reason_category: reason,
        reason_text: reasonText,
      });

      // 3. Decrypt escrow_wrap → KEK.
      const escrowWrap = fromBase64(resp.vault.escrow_wrap_b64);
      kekBytes = await aesGcmDecrypt(escrowWrap, escrowKey);

      // 4. Decrypt encrypted_x25519_privkey under KEK.
      const encPriv = fromBase64(resp.vault.encrypted_x25519_privkey_b64);
      privkey = await aesGcmDecrypt(encPriv, kekBytes);

      setRecovered({
        kekHex: toHex(kekBytes),
        privkeyHex: toHex(privkey),
        pubkeyHex: toHex(fromBase64(resp.vault.x25519_pubkey_b64)),
        audit: {
          unlock_log_id: resp.unlock_log_id,
          security_incident_id: resp.security_incident_id,
          severity: resp.severity,
          rkn_notify_required: resp.rkn_notify_required,
          created_at: resp.created_at,
        },
      });
    } catch (err) {
      setError(describeError(err));
    } finally {
      // Wipe sensitive material из локальной памяти (raw bytes); recovered
      // state contains hex strings (необходимы для UI display).
      escrowKey?.fill(0);
      kekBytes?.fill(0);
      privkey?.fill(0);
      setBusy(false);
    }
  };

  const handleClear = (): void => {
    // Drop recovered material from React state; admin export'нул KEK
    // already если нужно.
    setRecovered(null);
    setShare1("");
    setShare2("");
    setReasonText("");
    setTargetUserId("");
  };

  if (recovered) {
    return (
      <div className="space-y-4 rounded border border-gray-200 bg-white p-4">
        <h2 className="text-lg font-semibold text-green-900">
          ✓ Vault recovery успешна
        </h2>

        <section className="rounded border border-gray-200 bg-gray-50 p-3">
          <h3 className="text-sm font-semibold">Audit metadata</h3>
          <dl className="mt-2 grid grid-cols-2 gap-y-1 text-xs">
            <dt className="text-gray-600">Unlock log ID:</dt>
            <dd className="font-mono">{recovered.audit.unlock_log_id}</dd>
            <dt className="text-gray-600">Security incident ID:</dt>
            <dd className="font-mono">{recovered.audit.security_incident_id}</dd>
            <dt className="text-gray-600">Severity:</dt>
            <dd className="font-mono">{recovered.audit.severity}</dd>
            <dt className="text-gray-600">РКН notify required:</dt>
            <dd className="font-mono">
              {recovered.audit.rkn_notify_required ? "YES" : "no"}
            </dd>
            <dt className="text-gray-600">Created at:</dt>
            <dd className="font-mono">{recovered.audit.created_at}</dd>
          </dl>
        </section>

        <div className="rounded border border-red-200 bg-red-50 p-3 text-xs text-red-900">
          <strong>Внимание:</strong> ниже raw cryptographic material.
          Скопируйте в admin tool offline (e.g. secure terminal с
          envvar passthrough). НЕ скриншот, НЕ paste в Slack / email.
          После закрытия страницы — material исчезнет из браузера.
        </div>

        <section>
          <h3 className="text-sm font-semibold">Recovered KEK (hex)</h3>
          <pre
            data-testid="recovered-kek"
            className="rounded bg-gray-100 p-3 font-mono text-xs break-all whitespace-pre-wrap"
          >
            {recovered.kekHex}
          </pre>
        </section>

        <section>
          <h3 className="text-sm font-semibold">User X25519 privkey (hex)</h3>
          <pre
            data-testid="recovered-privkey"
            className="rounded bg-gray-100 p-3 font-mono text-xs break-all whitespace-pre-wrap"
          >
            {recovered.privkeyHex}
          </pre>
        </section>

        <section>
          <h3 className="text-sm font-semibold">User X25519 pubkey (hex, public)</h3>
          <pre
            data-testid="recovered-pubkey"
            className="rounded bg-gray-100 p-3 font-mono text-xs break-all whitespace-pre-wrap"
          >
            {recovered.pubkeyHex}
          </pre>
        </section>

        <button
          type="button"
          onClick={handleClear}
          className="rounded bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800"
        >
          Очистить + завершить
        </button>
      </div>
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-4 rounded border border-gray-200 bg-white p-4"
    >
      <h2 className="text-lg font-semibold">Emergency unlock vault</h2>
      <div className="rounded border border-yellow-200 bg-yellow-50 p-3 text-xs text-yellow-900">
        Ceremony requires 2 shares (директор + юрист) + audit-grade reason.
        Каждое использование triggers security_incident + audit row.
        Per ADR-0021 — backend никогда не видит shares; combine + decrypt
        выполняются в этом браузере.
      </div>

      <label className="block">
        <span className="text-sm font-medium">Target user ID (UUID)</span>
        <input
          type="text"
          value={targetUserId}
          onChange={(e) => setTargetUserId(e.target.value)}
          required
          autoComplete="off"
          placeholder="e.g. 12345678-1234-1234-1234-1234567890ab"
          className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm font-mono"
          disabled={busy}
        />
      </label>

      <label className="block">
        <span className="text-sm font-medium">Reason category</span>
        <select
          value={reason}
          onChange={(e) => setReason(e.target.value as EmergencyReasonCategory)}
          required
          className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm"
          disabled={busy}
        >
          {(Object.entries(REASON_LABELS) as [EmergencyReasonCategory, string][]).map(
            ([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ),
          )}
        </select>
      </label>

      <label className="block">
        <span className="text-sm font-medium">
          Reason details (мин. 10, макс. 2000 символов)
        </span>
        <textarea
          value={reasonText}
          onChange={(e) => setReasonText(e.target.value)}
          required
          minLength={10}
          maxLength={2000}
          rows={3}
          placeholder="Incident ID / case ID / legal order reference + контекст"
          className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm"
          disabled={busy}
        />
      </label>

      <label className="block">
        <span className="text-sm font-medium">Share 1 (директор)</span>
        <textarea
          value={share1}
          onChange={(e) => setShare1(e.target.value)}
          required
          rows={2}
          placeholder="base32 (whitespace + case OK)"
          className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-xs font-mono"
          disabled={busy}
        />
      </label>

      <label className="block">
        <span className="text-sm font-medium">Share 2 (юрист)</span>
        <textarea
          value={share2}
          onChange={(e) => setShare2(e.target.value)}
          required
          rows={2}
          placeholder="base32 (whitespace + case OK)"
          className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-xs font-mono"
          disabled={busy}
        />
      </label>

      {error && (
        <div
          role="alert"
          className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-900"
        >
          {error}
        </div>
      )}

      <button
        type="submit"
        disabled={busy || !share1 || !share2 || reasonText.length < 10}
        className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
      >
        {busy ? "Recovery..." : "Combine shares + recover"}
      </button>
    </form>
  );
}
