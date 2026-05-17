/**
 * Public onboarding landing для коллаборантов (ADR-0015 §6, ТЗ §10.8.1).
 *
 * Anonymous (без auth) — pre-renders на server side, форма hydrate'ится на
 * клиенте. Доступна по `/onboarding/collaborator` без header / nav (намеренно
 * чистая лендинг-страница, чтобы не отвлекать).
 */

import type { Metadata } from "next";

import OnboardingForm from "./_components/onboarding-form";

export const metadata: Metadata = {
  title: "Стать партнёром reHome",
  description:
    "Подайте заявку на сотрудничество: УК, аварийные службы, клининг, ремонт, переезды и другие услуги.",
  robots: { index: true, follow: true },
};

export default function OnboardingLandingPage(): JSX.Element {
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-10">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold tracking-tight">
          Стать партнёром reHome
        </h1>
        <p className="text-sm text-gray-700">
          reHome — платформа долгосрочной аренды жилья без залога. Мы ищем
          надёжных партнёров: управляющие компании, аварийные службы,
          ремонтных специалистов, клининг, переезды и другие услуги. Заполните
          форму — сотрудник свяжется в течение 1–3 рабочих дней.
        </p>
      </header>

      <section className="rounded-md border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900">
        <h2 className="font-medium">Что важно знать заранее</h2>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-xs">
          <li>
            Активация заявки требует ручной проверки контакта и контрагента
            (Dadata / ЕГРЮЛ). Эта проверка — на нашей стороне.
          </li>
          <li>
            Финансовая схема (мы платим вам / вы платите нам комиссию /
            реферальная / бесплатный контакт) определяется типом услуг.
          </li>
          <li>
            Передавая контактные данные, вы соглашаетесь с обработкой
            персональных данных по ФЗ-152.
          </li>
        </ul>
      </section>

      <OnboardingForm />

      <p className="text-xs text-gray-500">
        Не получается отправить форму? Напишите на{" "}
        <a
          href="mailto:partners@rehome.example"
          className="underline hover:text-gray-700"
        >
          partners@rehome.example
        </a>
        .
      </p>
    </main>
  );
}
