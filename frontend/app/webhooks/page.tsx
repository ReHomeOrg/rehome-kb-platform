/**
 * /webhooks — управление webhook subscriptions (UI.7 #95).
 *
 * Server Component shell: fetches list через SSR, рендерит header +
 * create form + table. Interaktive parts (delete/test/create) — Client
 * Components с router.refresh() после mutate.
 */

import { redirect } from "next/navigation";

import Nav from "@/app/_components/nav";
import { ApiError } from "@/lib/api/client";
import { listWebhooks } from "@/lib/api/webhooks";

import CreateForm from "./_components/create-form";
import WebhooksTable from "./_components/webhooks-table";

export default async function WebhooksPage(): Promise<JSX.Element> {
  let webhooks;
  try {
    webhooks = (await listWebhooks()).data;
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      redirect("/login?next=/webhooks");
    }
    throw err;
  }

  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-5xl flex-col gap-8 px-6 py-8">
        <header>
          <h1 className="text-2xl font-semibold tracking-tight">Webhooks</h1>
          <p className="mt-1 text-sm text-gray-600">
            Подписки на системные события. POST на ваш URL с HMAC-SHA256
            подписью в заголовке <code>X-Rehome-Signature</code>.
          </p>
        </header>

        <section className="flex flex-col gap-3">
          <h2 className="text-lg font-medium">Новая подписка</h2>
          <CreateForm />
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-lg font-medium">
            Активные подписки ({webhooks.length})
          </h2>
          <WebhooksTable webhooks={webhooks} />
        </section>
      </main>
    </>
  );
}
