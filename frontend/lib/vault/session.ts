/**
 * Vault session — in-memory non-extractable CryptoKey store (ADR-0016 §D).
 *
 * Lifetime:
 * - `setVaultKey(key)` после успешного unlock'а.
 * - Auto-lock через `AUTO_LOCK_MS` (15 min) inactivity.
 * - `clearVaultKey()` при logout / lock button.
 * - Module-level variable: closed-over по design; не persisted в
 *   localStorage / IndexedDB / cookies (ADR-0016 §«State management»).
 *
 * Listeners — для React UI: компонент подписывается, перерисовывается
 * при locked/unlocked transitions.
 *
 * Note: тестируется в jsdom без таймеров (тестируем pure store без
 * 15-min wait); в production браузерный timer переключает на locked
 * автоматически.
 */

export const AUTO_LOCK_MS = 15 * 60 * 1000;

type Listener = () => void;

let vaultKey: CryptoKey | null = null;
let autoLockTimer: ReturnType<typeof setTimeout> | null = null;
const listeners = new Set<Listener>();

function notify(): void {
  listeners.forEach((l) => {
    try {
      l();
    } catch {
      // Listeners must not throw — defensive swallow (UI render errors
      // are logged elsewhere).
    }
  });
}

function resetAutoLock(): void {
  if (autoLockTimer !== null) {
    clearTimeout(autoLockTimer);
    autoLockTimer = null;
  }
  if (vaultKey !== null) {
    autoLockTimer = setTimeout(() => {
      vaultKey = null;
      autoLockTimer = null;
      notify();
    }, AUTO_LOCK_MS);
  }
}

/** Store vault key after successful unlock. Caller передаёт
 * non-extractable CryptoKey (получен от `deriveKeys`). */
export function setVaultKey(key: CryptoKey): void {
  vaultKey = key;
  resetAutoLock();
  notify();
}

/** Get current vault key or null если locked. */
export function getVaultKey(): CryptoKey | null {
  return vaultKey;
}

/** True если vault разблокирован. */
export function isUnlocked(): boolean {
  return vaultKey !== null;
}

/** Manual lock — clears vaultKey + cancels auto-lock timer. */
export function lock(): void {
  vaultKey = null;
  if (autoLockTimer !== null) {
    clearTimeout(autoLockTimer);
    autoLockTimer = null;
  }
  notify();
}

/** Reset auto-lock timer (e.g., после user activity в vault UI). */
export function touch(): void {
  if (vaultKey !== null) {
    resetAutoLock();
  }
}

/** Subscribe для UI re-render при locked/unlocked transitions. */
export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
