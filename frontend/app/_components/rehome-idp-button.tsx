/**
 * Кнопка «Авторизация в rehome» (brokered-login со стейджинговой платформой).
 *
 * Инициирует OIDC-вход через upstream-IdP Keycloak (`kc_idp_hint`): при активной
 * сессии платформы — silent SSO. Рендерится ТОЛЬКО если задан alias IdP
 * (`NEXT_PUBLIC_REHOME_IDP_HINT` из allowlist) — на прод-сборке флага нет → `null`
 * (кнопки нет, прод-UI неизменен). Показывать только анониму (вызывающий решает по
 * isLoggedIn). Прав не выдаёт — лишь инициирует вход; access_level считает бэкенд.
 */

import { getRehomeIdpHint } from "@/lib/auth/config";
import { BASE_PATH } from "@/lib/base-path";

export function RehomeIdpButton(): JSX.Element | null {
  const hint = getRehomeIdpHint();
  if (!hint) {
    return null;
  }
  return (
    <a
      href={`${BASE_PATH}/api/auth/login?kc_idp_hint=${hint}`}
      className="rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
    >
      Авторизация в rehome
    </a>
  );
}
