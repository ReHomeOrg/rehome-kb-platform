"use client";

/**
 * Unlocked vault view (ADR-0016 Slices 2-4).
 *
 * Compoposes:
 * - Lock button.
 * - Tab nav: Секреты / Группы / Безопасность.
 * - Secrets tab: CreateSecretForm + SecretsList.
 * - Groups tab: GroupsPanel.
 * - Security tab: TOTP management (enable/disable).
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import { disableTotp } from "@/lib/api/vault";
import { lock, touch } from "@/lib/vault/session";

import CreateSecretForm from "./create-secret-form";
import ExpirySummary from "./expiry-summary";
import Fido2KeysPanel from "./fido2-keys-panel";
import GroupsPanel from "./groups-panel";
import SecretsList from "./secrets-list";
import TotpSetupForm from "./totp-setup-form";

type Tab = "secrets" | "groups" | "security";

interface Props {
  userId: string;
  hasTotp: boolean;
}

export default function UnlockedView({ userId, hasTotp }: Props): JSX.Element {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("secrets");
  const [showCreate, setShowCreate] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  const [showTotpSetup, setShowTotpSetup] = useState(false);
  const [totpDisabling, setTotpDisabling] = useState(false);
  const [totpError, setTotpError] = useState<string | null>(null);

  async function onDisableTotp(): Promise<void> {
    if (totpDisabling) return;
    if (!window.confirm("Отключить TOTP 2FA?")) return;
    setTotpDisabling(true);
    setTotpError(null);
    try {
      await disableTotp();
      router.refresh();
    } catch (err) {
      if (err instanceof ApiError) {
        setTotpError(`${err.status}: ${err.message}`);
      } else {
        setTotpError(err instanceof Error ? err.message : "Ошибка");
      }
    } finally {
      setTotpDisabling(false);
    }
  }

  return (
    <section
      className="flex flex-col gap-4 rounded-md border border-green-300 bg-green-50 p-6"
      onClick={() => touch()}
    >
      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-green-900">
            Vault разблокирован
          </h2>
          <p className="text-xs text-green-800">
            Auto-lock через 15 минут бездействия. Каждый просмотр секрета
            журналируется на сервере (ПЗ §8).
          </p>
        </div>
        <button
          type="button"
          onClick={() => lock()}
          className="shrink-0 rounded-md border border-green-300 bg-white px-3 py-1.5 text-sm font-medium text-green-800 hover:bg-green-100"
        >
          Заблокировать
        </button>
      </header>

      <nav className="flex gap-2 border-b border-green-300">
        <TabButton current={tab} value="secrets" label="Секреты" onClick={setTab} />
        <TabButton current={tab} value="groups" label="Группы" onClick={setTab} />
        <TabButton
          current={tab}
          value="security"
          label={hasTotp ? "Безопасность · 2FA" : "Безопасность"}
          onClick={setTab}
        />
      </nav>

      <div className="rounded-md bg-white p-4">
        {tab === "secrets" ? (
          <>
            <ExpirySummary
              reloadToken={reloadToken}
              onJumpToSecrets={undefined}
            />
            {showCreate ? (
              <CreateSecretForm
                userId={userId}
                onCancel={() => setShowCreate(false)}
                onSuccess={() => {
                  setShowCreate(false);
                  setReloadToken((n) => n + 1);
                }}
              />
            ) : null}
            <SecretsList
              onCreateClick={() => setShowCreate(true)}
              reloadToken={reloadToken}
            />
          </>
        ) : tab === "groups" ? (
          <GroupsPanel currentUserId={userId} />
        ) : (
          <div className="flex flex-col gap-3">
            <h3 className="text-sm font-medium text-gray-700">
              Двухфакторная аутентификация (TOTP)
            </h3>
            {hasTotp ? (
              <>
                <p className="rounded-md border border-green-200 bg-green-50 p-2 text-xs text-green-900">
                  ✓ 2FA включена. При unlock&apos;е после ввода master password
                  потребуется код из приложения-аутентификатора.
                </p>
                <button
                  type="button"
                  onClick={() => void onDisableTotp()}
                  disabled={totpDisabling}
                  className="self-start rounded-md border border-red-300 bg-red-50 px-3 py-1.5 text-xs font-medium text-red-800 hover:bg-red-100 disabled:opacity-50"
                >
                  {totpDisabling ? "Отключаем…" : "Отключить 2FA"}
                </button>
                {totpError ? (
                  <p
                    role="alert"
                    className="rounded-md border border-red-200 bg-red-50 px-2 py-1 text-xs text-red-700"
                  >
                    {totpError}
                  </p>
                ) : null}
              </>
            ) : showTotpSetup ? (
              <TotpSetupForm
                accountLabel={`vault-${userId.slice(0, 8)}`}
                onCancel={() => setShowTotpSetup(false)}
                onSuccess={() => {
                  setShowTotpSetup(false);
                  router.refresh();
                }}
              />
            ) : (
              <>
                <p className="text-xs text-gray-600">
                  Без 2FA любой, кто узнал ваш master password, может
                  разблокировать vault. Рекомендуем включить TOTP — это
                  второй уровень защиты через приложение-аутентификатор.
                </p>
                <button
                  type="button"
                  onClick={() => setShowTotpSetup(true)}
                  className="self-start rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800"
                >
                  Включить 2FA
                </button>
              </>
            )}

            <div className="mt-6 border-t border-gray-200 pt-6">
              <Fido2KeysPanel />
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

interface TabBtnProps {
  current: Tab;
  value: Tab;
  label: string;
  onClick: (value: Tab) => void;
}

function TabButton({ current, value, label, onClick }: TabBtnProps): JSX.Element {
  return (
    <button
      type="button"
      onClick={() => onClick(value)}
      className={`-mb-px border-b-2 px-3 py-1.5 text-sm font-medium ${
        current === value
          ? "border-gray-900 text-gray-900"
          : "border-transparent text-gray-600 hover:text-gray-900"
      }`}
    >
      {label}
    </button>
  );
}
