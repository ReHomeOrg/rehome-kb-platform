/**
 * Pure helpers для PremisesForm (#200).
 *
 * Extracted из premises-form.tsx чтобы unit-testable без mount'инга
 * полного Client Component'а с useState/router/fetch dependencies.
 */

/**
 * Сериализует value в pretty JSON для textarea. null / undefined /
 * empty object → пустая строка (textarea показывает placeholder).
 */
export function jsonToString(value: unknown): string {
  if (
    value == null ||
    (typeof value === "object" && Object.keys(value).length === 0)
  ) {
    return "";
  }
  return JSON.stringify(value, null, 2);
}

/**
 * Парсит textarea content в JSON object для отправки на backend.
 *
 * Returns:
 * - `null` — пустой ввод (поле не задано)
 * - `Record<string, unknown>` — успешный parse JSON object'а
 * - `string` — error message (validation failed)
 *
 * Array/primitive valid JSON НЕ принимаются — backend ожидает object.
 */
export function parseJsonOrNull(
  str: string,
): Record<string, unknown> | null | string {
  const trimmed = str.trim();
  if (!trimmed) return null;
  try {
    const parsed = JSON.parse(trimmed) as unknown;
    if (parsed === null || (typeof parsed === "object" && !Array.isArray(parsed))) {
      return parsed as Record<string, unknown> | null;
    }
    return "must be JSON object";
  } catch {
    return "invalid JSON";
  }
}
