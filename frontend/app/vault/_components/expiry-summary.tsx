"use client";

/**
 * Rotation reminders banner (ADR-0016 Slice 5).
 *
 * Без backend additions — fetches `/vault/secrets` (metadata only,
 * без crypto cost), считает секреты с `expires_at` в окно <= 30 дней
 * либо уже истекшие.
 *
 * Banner hidden если нечего показать. По клику — переключается на
 * Секреты таб (через onJump prop).
 */

import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  listVaultSecrets,
  type VaultSecretMetadataView,
} from "@/lib/api/vault";

const EXPIRING_WINDOW_DAYS = 30;
const MS_PER_DAY = 24 * 60 * 60 * 1000;

interface Props {
  /** Bump для re-fetch (когда секрет created / updated / deleted). */
  reloadToken: number;
  /** Callback для navigate'а на Секреты таб (если caller хочет). */
  onJumpToSecrets?: () => void;
}

interface Buckets {
  expiringSoon: VaultSecretMetadataView[];
  expired: VaultSecretMetadataView[];
}

function bucketize(rows: VaultSecretMetadataView[]): Buckets {
  const now = Date.now();
  const expiringSoon: VaultSecretMetadataView[] = [];
  const expired: VaultSecretMetadataView[] = [];
  for (const r of rows) {
    if (!r.expires_at || r.archived_at) continue;
    const ms = new Date(r.expires_at).getTime();
    if (Number.isNaN(ms)) continue;
    if (ms < now) {
      expired.push(r);
    } else if (ms - now < EXPIRING_WINDOW_DAYS * MS_PER_DAY) {
      expiringSoon.push(r);
    }
  }
  return { expiringSoon, expired };
}

export default function ExpirySummary({
  reloadToken,
  onJumpToSecrets,
}: Props): JSX.Element | null {
  const [buckets, setBuckets] = useState<Buckets | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load(): Promise<void> {
      try {
        const resp = await listVaultSecrets();
        if (!cancelled) setBuckets(bucketize(resp.data));
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError) {
          setError(`${err.status}: ${err.message}`);
        } else {
          setError(err instanceof Error ? err.message : "Ошибка");
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [reloadToken]);

  if (error) {
    return (
      <p
        role="alert"
        data-testid="expiry-error"
        className="rounded-md border border-red-200 bg-red-50 p-2 text-xs text-red-700"
      >
        {error}
      </p>
    );
  }

  if (buckets === null) {
    return null;
  }

  const expiringCount = buckets.expiringSoon.length;
  const expiredCount = buckets.expired.length;
  if (expiringCount === 0 && expiredCount === 0) {
    return null;
  }

  return (
    <div
      role="status"
      data-testid="expiry-summary"
      className="flex items-start justify-between gap-3 rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900"
    >
      <div>
        <p className="font-medium">Ротация секретов</p>
        <p className="mt-1">
          {expiredCount > 0
            ? `${expiredCount} ${pluralize(expiredCount, "секрет", "секрета", "секретов")} уже истёк${expiredCount === 1 ? "" : "ли"}.`
            : null}{" "}
          {expiringCount > 0
            ? `${expiringCount} ${pluralize(expiringCount, "секрет истекает", "секрета истекают", "секретов истекают")} в ближайшие ${EXPIRING_WINDOW_DAYS} дней.`
            : null}
        </p>
      </div>
      {onJumpToSecrets ? (
        <button
          type="button"
          onClick={onJumpToSecrets}
          className="shrink-0 rounded-md border border-amber-400 bg-white px-2 py-1 text-xs font-medium text-amber-900 hover:bg-amber-100"
        >
          Открыть секреты
        </button>
      ) : null}
    </div>
  );
}

function pluralize(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few;
  return many;
}
