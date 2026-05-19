/**
 * /admin/system-config — read-only system config view (#252, backend #229).
 *
 * staff_admin scope. PATCH endpoint — backlog (ADR-0019 — writable
 * runtime config storage).
 */

import Nav from "@/app/_components/nav";
import { getSystemConfig } from "@/lib/api/admin-system-config";
import { ApiError } from "@/lib/api/client";
import type { SystemConfig } from "@/lib/api/types";

function formatNullable(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return v.toString();
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}): JSX.Element {
  return (
    <section className="mb-6 rounded-md border border-gray-200 bg-white">
      <h2 className="border-b border-gray-200 bg-gray-50 px-4 py-2 text-sm font-medium text-gray-700">
        {title}
      </h2>
      <div className="p-4">{children}</div>
    </section>
  );
}

function KV({ label, value }: { label: string; value: string }): JSX.Element {
  return (
    <div className="flex justify-between gap-4 border-t border-gray-100 py-1.5 text-xs first:border-t-0">
      <dt className="text-gray-600">{label}</dt>
      <dd className="font-mono text-gray-900">{value}</dd>
    </div>
  );
}

export default async function SystemConfigPage(): Promise<JSX.Element> {
  let config: SystemConfig | undefined;
  let error: string | undefined;
  try {
    config = await getSystemConfig();
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 401 || e.status === 403) {
        error = "Доступ только для staff_admin.";
      } else {
        error = `Ошибка ${e.status}: ${e.message}`;
      }
    } else {
      error = "Не удалось загрузить конфигурацию.";
    }
  }

  return (
    <>
      <Nav />
      <main className="mx-auto max-w-4xl px-4 py-6">
        <h1 className="mb-2 text-2xl font-semibold">System config</h1>
        <p className="mb-4 text-sm text-gray-600">
          OpenAPI 04 §getSystemConfig. Read-only projection текущего env
          + runtime overlay. PATCH (мутация) — backlog (ADR-0019).
        </p>

        {error !== undefined ? (
          <div
            role="alert"
            className="mb-4 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-900"
          >
            {error}
          </div>
        ) : null}

        {config ? (
          <>
            <Section title="LLM">
              <dl>
                <KV label="active_provider" value={config.llm_config.active_provider} />
                <KV
                  label="fallback_provider"
                  value={config.llm_config.fallback_provider ?? "—"}
                />
                <KV
                  label="ab_test_split_percent"
                  value={formatNullable(config.llm_config.ab_test_split_percent)}
                />
                <KV
                  label="max_context_tokens"
                  value={formatNullable(config.llm_config.max_context_tokens)}
                />
                <KV
                  label="temperature"
                  value={formatNullable(config.llm_config.temperature)}
                />
              </dl>
            </Section>

            <Section title="Feature flags">
              <dl>
                {Object.entries(config.feature_flags).length === 0 ? (
                  <div className="text-xs text-gray-500">Нет флагов.</div>
                ) : (
                  Object.entries(config.feature_flags).map(([key, value]) => (
                    <KV key={key} label={key} value={value ? "true" : "false"} />
                  ))
                )}
              </dl>
            </Section>

            <Section title="Rate limits">
              <dl>
                <KV
                  label="guest_per_minute"
                  value={formatNullable(config.rate_limits.guest_per_minute)}
                />
                <KV
                  label="user_per_minute"
                  value={formatNullable(config.rate_limits.user_per_minute)}
                />
                <KV
                  label="m2m_per_minute"
                  value={formatNullable(config.rate_limits.m2m_per_minute)}
                />
                <KV
                  label="chat_messages_per_5min"
                  value={formatNullable(config.rate_limits.chat_messages_per_5min)}
                />
              </dl>
            </Section>

            <Section title="Webhooks">
              <dl>
                <KV
                  label="max_retries"
                  value={config.webhooks.max_retries.toString()}
                />
                <KV
                  label="timeout_seconds"
                  value={config.webhooks.timeout_seconds.toString()}
                />
              </dl>
            </Section>

            <Section title="Moderation">
              <dl>
                <KV
                  label="auto_publish_threshold"
                  value={formatNullable(config.moderation.auto_publish_threshold)}
                />
                <KV
                  label="require_review_for_categories"
                  value={
                    config.moderation.require_review_for_categories.length === 0
                      ? "[]"
                      : config.moderation.require_review_for_categories.join(", ")
                  }
                />
              </dl>
            </Section>
          </>
        ) : null}
      </main>
    </>
  );
}
