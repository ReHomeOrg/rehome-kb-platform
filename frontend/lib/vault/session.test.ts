/**
 * Vault session store tests. Auto-lock taймер тестируем через
 * vi.useFakeTimers — реальный 15-min wait в CI неприемлемо.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AUTO_LOCK_MS,
  getVaultKey,
  isUnlocked,
  lock,
  setVaultKey,
  subscribe,
  touch,
} from "./session";

async function makeFakeKey(): Promise<CryptoKey> {
  return crypto.subtle.generateKey(
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
}

describe("vault session", () => {
  beforeEach(() => {
    lock(); // reset state
    vi.useFakeTimers();
  });

  afterEach(() => {
    lock();
    vi.useRealTimers();
  });

  it("isUnlocked=false initially", () => {
    expect(isUnlocked()).toBe(false);
    expect(getVaultKey()).toBeNull();
  });

  it("setVaultKey makes vault unlocked", async () => {
    const k = await makeFakeKey();
    setVaultKey(k);
    expect(isUnlocked()).toBe(true);
    expect(getVaultKey()).toBe(k);
  });

  it("auto-locks после AUTO_LOCK_MS inactivity", async () => {
    const k = await makeFakeKey();
    setVaultKey(k);
    vi.advanceTimersByTime(AUTO_LOCK_MS - 1);
    expect(isUnlocked()).toBe(true);
    vi.advanceTimersByTime(1);
    expect(isUnlocked()).toBe(false);
  });

  it("touch() resets auto-lock timer", async () => {
    const k = await makeFakeKey();
    setVaultKey(k);
    vi.advanceTimersByTime(AUTO_LOCK_MS - 100);
    touch();
    // Past original deadline, но touch() reset'нул.
    vi.advanceTimersByTime(200);
    expect(isUnlocked()).toBe(true);
    // Должен зафейлить через AUTO_LOCK_MS от touch'а.
    vi.advanceTimersByTime(AUTO_LOCK_MS);
    expect(isUnlocked()).toBe(false);
  });

  it("touch() noop когда locked", () => {
    touch(); // не должен ставить таймер
    expect(isUnlocked()).toBe(false);
    vi.advanceTimersByTime(AUTO_LOCK_MS + 1000);
    expect(isUnlocked()).toBe(false);
  });

  it("manual lock() clears vaultKey + notifies subscribers", async () => {
    const k = await makeFakeKey();
    const listener = vi.fn();
    const unsub = subscribe(listener);
    setVaultKey(k);
    expect(listener).toHaveBeenCalledTimes(1);
    lock();
    expect(listener).toHaveBeenCalledTimes(2);
    expect(isUnlocked()).toBe(false);
    unsub();
  });

  it("subscribers notified на auto-lock", async () => {
    const k = await makeFakeKey();
    const listener = vi.fn();
    subscribe(listener);
    setVaultKey(k);
    listener.mockClear();
    vi.advanceTimersByTime(AUTO_LOCK_MS);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("subscribe returns cleanup that removes listener", async () => {
    const k = await makeFakeKey();
    const listener = vi.fn();
    const unsub = subscribe(listener);
    unsub();
    setVaultKey(k);
    expect(listener).not.toHaveBeenCalled();
  });
});
