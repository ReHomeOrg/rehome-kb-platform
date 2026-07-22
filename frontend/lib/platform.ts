/**
 * Origin основной платформы reHome (rehome.one).
 *
 * Help-центр встроен под `rehome.one/help` и делит домен с платформой. Вход и
 * регистрация — единые, на платформе (phone-first Django-сессия), а НЕ в
 * отдельном Keycloak help-центра: у прод-пользователей Keycloak-аккаунта нет.
 * Поэтому login-CTA help-центра ведут на модалку входа платформы.
 *
 * Параметризовано env (`NEXT_PUBLIC_PLATFORM_ORIGIN`, build-time) — чтобы
 * stage/preview могли указывать на свой origin; дефолт — прод-домен.
 */
export const PLATFORM_ORIGIN =
  process.env.NEXT_PUBLIC_PLATFORM_ORIGIN ?? "https://rehome.one";

/**
 * URL модалки входа платформы. `AuthWidget` на главной слушает `?auth=login`
 * и открывает попап входа/регистрации.
 */
export const PLATFORM_LOGIN_URL = `${PLATFORM_ORIGIN}/?auth=login`;
