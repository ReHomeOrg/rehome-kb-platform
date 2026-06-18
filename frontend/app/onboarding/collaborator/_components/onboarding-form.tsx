"use client";

/**
 * Public onboarding form (ADR-0015 §6, ТЗ §10.8.1).
 *
 * Anonymous (без auth) — отправляет на `POST /api/v1/collaborators/onboarding`.
 * Backend применяет rate-limit (5 заявок/час/IP) + anti-enumeration mask
 * в response. UI отображает только success / generic error / rate-limit.
 *
 * Important UX:
 * - `type='other'` запрещён через self-form (ADR-0015 §6) — backend 422.
 *   В UI исключаем из select.
 * - Хотя бы один контакт (phone/email/messenger) обязателен — валидируем
 *   локально + backend re-checks.
 * - Success message — generic, не показываем id/status (anti-enum).
 */

import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  submitOnboarding,
  type OnboardingContact,
  type OnboardingRequest,
  type PortalAccessLevel,
} from "@/lib/api/collaborators";
import type {
  CollaboratorLegalEntityType,
  CollaboratorType,
} from "@/lib/api/types";

// `other` исключён — ADR-0015 §6: требует staff_invite, не self-form.
const SELF_FORM_TYPES: Exclude<CollaboratorType, "other">[] = [
  "management_company",
  "emergency_service",
  "repair_handyman",
  "cleaning",
  "moving",
  "key_delivery",
  "insurance",
  "payment_partner",
  "kyc_provider",
  "edo_provider",
  "sms_voice",
  "it_infrastructure",
  "legal_consultant",
];

const TYPE_LABELS: Record<Exclude<CollaboratorType, "other">, string> = {
  management_company: "Управляющая компания",
  emergency_service: "Аварийная служба",
  repair_handyman: "Ремонт / сантехник / электрик",
  cleaning: "Клининг",
  moving: "Переезды",
  key_delivery: "Доставка ключей",
  insurance: "Страхование",
  payment_partner: "Платёжный партнёр",
  kyc_provider: "KYC-провайдер",
  edo_provider: "ЭДО-провайдер",
  sms_voice: "SMS / голос",
  it_infrastructure: "IT-инфраструктура",
  legal_consultant: "Юр. консультант",
};

const LEGAL_TYPES: { value: CollaboratorLegalEntityType; label: string }[] = [
  { value: "individual", label: "Физлицо" },
  { value: "self_employed", label: "Самозанятый" },
  { value: "ip", label: "ИП" },
  { value: "legal_entity", label: "Юр. лицо" },
];

const PORTAL_LEVELS: { value: PortalAccessLevel; label: string }[] = [
  { value: "NONE", label: "NONE — без кабинета" },
  { value: "LIGHT", label: "LIGHT — просмотр заявок" },
  { value: "FULL", label: "FULL — полный кабинет" },
];

export default function OnboardingForm(): JSX.Element {
  const [name, setName] = useState("");
  const [brandName, setBrandName] = useState("");
  const [type, setType] = useState<Exclude<CollaboratorType, "other">>(
    "management_company",
  );
  const [legalEntityType, setLegalEntityType] = useState<
    CollaboratorLegalEntityType | ""
  >("");
  const [inn, setInn] = useState("");
  const [serviceArea, setServiceArea] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [messenger, setMessenger] = useState("");
  const [personName, setPersonName] = useState("");
  const [personRole, setPersonRole] = useState("");
  const [portalLevel, setPortalLevel] = useState<PortalAccessLevel>("LIGHT");
  const [message, setMessage] = useState("");

  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  async function onSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    setError(null);

    if (!phone.trim() && !email.trim() && !messenger.trim()) {
      setError(
        "Укажите хотя бы один контакт: телефон, email или мессенджер.",
      );
      return;
    }

    const contact: OnboardingContact = {
      phone: phone.trim() || null,
      email: email.trim() || null,
      messenger: messenger.trim() || null,
      person_name: personName.trim() || null,
      person_role: personRole.trim() || null,
    };

    const payload: OnboardingRequest = {
      name: name.trim(),
      brand_name: brandName.trim() || null,
      type,
      legal_entity_type: legalEntityType || null,
      inn: inn.trim() || null,
      service_area: serviceArea.trim(),
      contact,
      portal_access_level_requested: portalLevel,
      message: message.trim() || null,
    };

    setPending(true);
    try {
      await submitOnboarding(payload);
      setSubmitted(true);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 429) {
          setError(
            "Слишком много заявок с вашего IP. Попробуйте через час либо свяжитесь напрямую: partners@rehome.example.",
          );
        } else if (err.status === 422) {
          const body = err.body as { detail?: unknown } | null;
          const detail =
            typeof body?.detail === "string"
              ? body.detail
              : "Проверьте поля формы.";
          setError(`Невалидные данные: ${detail}`);
        } else {
          setError(
            `Не удалось отправить заявку (код ${err.status}). Попробуйте позже.`,
          );
        }
      } else {
        setError("Сеть недоступна. Попробуйте позже.");
      }
    } finally {
      setPending(false);
    }
  }

  if (submitted) {
    return (
      <div
        role="status"
        className="rounded-md border border-green-300 bg-green-50 p-6"
      >
        <h2 className="text-lg font-semibold text-green-900">
          Заявка отправлена
        </h2>
        <p className="mt-2 text-sm text-green-800">
          Мы свяжемся с вами по указанному контакту в течение 1–3 рабочих
          дней. Если потребуется дополнительная информация, наш сотрудник
          напишет напрямую.
        </p>
        <p className="mt-3 text-xs text-green-700">
          ID заявки не отображается из соображений безопасности — повторная
          подача не нужна.
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <fieldset className="flex flex-col gap-3 rounded-md border border-gray-200 p-4">
        <legend className="px-1 text-sm font-medium text-gray-700">
          О компании / ИП
        </legend>
        <label className="flex flex-col gap-1 text-sm">
          <span>
            Юр. название <span className="text-red-700">*</span>
          </span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            minLength={2}
            maxLength={500}
            required
            className="rounded-md border border-gray-300 px-3 py-1.5"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span>Бренд (если отличается от юр. названия)</span>
          <input
            type="text"
            value={brandName}
            onChange={(e) => setBrandName(e.target.value)}
            maxLength={200}
            className="rounded-md border border-gray-300 px-3 py-1.5"
          />
        </label>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-sm">
            <span>
              Тип услуг <span className="text-red-700">*</span>
            </span>
            <select
              value={type}
              onChange={(e) =>
                setType(
                  e.target.value as Exclude<CollaboratorType, "other">,
                )
              }
              className="rounded-md border border-gray-300 px-3 py-1.5"
            >
              {SELF_FORM_TYPES.map((t) => (
                <option key={t} value={t}>
                  {TYPE_LABELS[t]}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span>Форма</span>
            <select
              value={legalEntityType}
              onChange={(e) =>
                setLegalEntityType(
                  e.target.value as CollaboratorLegalEntityType | "",
                )
              }
              className="rounded-md border border-gray-300 px-3 py-1.5"
            >
              <option value="">не указано</option>
              {LEGAL_TYPES.map((l) => (
                <option key={l.value} value={l.value}>
                  {l.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-sm">
            <span>ИНН (10 или 12 цифр)</span>
            <input
              type="text"
              value={inn}
              onChange={(e) => setInn(e.target.value)}
              pattern="^\d{10}$|^\d{12}$"
              maxLength={12}
              className="rounded-md border border-gray-300 px-3 py-1.5"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span>
              География работы <span className="text-red-700">*</span>
            </span>
            <input
              type="text"
              value={serviceArea}
              onChange={(e) => setServiceArea(e.target.value)}
              minLength={3}
              maxLength={500}
              required
              placeholder="Москва ЦАО / Москва+МО / Россия"
              className="rounded-md border border-gray-300 px-3 py-1.5"
            />
          </label>
        </div>
      </fieldset>

      <fieldset className="flex flex-col gap-3 rounded-md border border-gray-200 p-4">
        <legend className="px-1 text-sm font-medium text-gray-700">
          Контакт <span className="text-xs text-gray-500">(минимум 1 канал)</span>
        </legend>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <label className="flex flex-col gap-1 text-sm">
            <span>Телефон</span>
            <input
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              maxLength={50}
              placeholder="+7 999 123-45-67"
              className="rounded-md border border-gray-300 px-3 py-1.5"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span>Email</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              maxLength={200}
              className="rounded-md border border-gray-300 px-3 py-1.5"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span>Мессенджер</span>
            <input
              type="text"
              value={messenger}
              onChange={(e) => setMessenger(e.target.value)}
              maxLength={200}
              placeholder="@telegram или wa.me/..."
              className="rounded-md border border-gray-300 px-3 py-1.5"
            />
          </label>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-sm">
            <span>Контактное лицо</span>
            <input
              type="text"
              value={personName}
              onChange={(e) => setPersonName(e.target.value)}
              maxLength={200}
              className="rounded-md border border-gray-300 px-3 py-1.5"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span>Должность</span>
            <input
              type="text"
              value={personRole}
              onChange={(e) => setPersonRole(e.target.value)}
              maxLength={100}
              placeholder="Менеджер по партнёрствам"
              className="rounded-md border border-gray-300 px-3 py-1.5"
            />
          </label>
        </div>
      </fieldset>

      <fieldset className="flex flex-col gap-3 rounded-md border border-gray-200 p-4">
        <legend className="px-1 text-sm font-medium text-gray-700">
          Кабинет и сообщение
        </legend>
        <label className="flex flex-col gap-1 text-sm">
          <span>Желаемый уровень кабинета</span>
          <select
            value={portalLevel}
            onChange={(e) => setPortalLevel(e.target.value as PortalAccessLevel)}
            className="rounded-md border border-gray-300 px-3 py-1.5"
          >
            {PORTAL_LEVELS.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </select>
          <span className="text-xs text-gray-500">
            Окончательный уровень утверждает сотрудник reHome при активации.
          </span>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span>Дополнительное сообщение</span>
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            rows={3}
            maxLength={2000}
            className="rounded-md border border-gray-300 px-3 py-1.5"
            placeholder="Кратко опишите услуги, опыт, тарифы."
          />
        </label>
      </fieldset>

      {error ? (
        <p
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700"
        >
          {error}
        </p>
      ) : null}

      <button
        type="submit"
        disabled={pending}
        className="self-start rounded-md bg-brand px-5 py-2 text-sm font-medium text-ink hover:bg-brand-hover disabled:opacity-50"
      >
        {pending ? "Отправляем…" : "Отправить заявку"}
      </button>
    </form>
  );
}
