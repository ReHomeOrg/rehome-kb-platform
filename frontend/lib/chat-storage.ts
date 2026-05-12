/**
 * localStorage helpers для chat session_token (UI.4 #81).
 *
 * Anonymous chat-сессии — backend выдаёт opaque session_token при POST
 * /chat/sessions, client должен слать его в X-Chat-Session-Token header
 * для последующих read/write операций.
 *
 * Token storage trade-off: localStorage (JS-accessible) — простой и
 * shareable между tabs. Theft localStorage = hijack ОДНОЙ chat-сессии,
 * не user account. session.expires_at = 24h на backend. Acceptable
 * для MVP.
 *
 * Альтернативы (backlog): HttpOnly cookie с Next.js API route чтобы
 * клиент не имел доступа к token.
 */

const SESSION_TOKENS_KEY = "rehome_chat_session_tokens";
const RECENT_SESSIONS_KEY = "rehome_chat_recent_sessions";

interface RecentSessionMeta {
  id: string;
  created_at: string;
  scope: string;
}

interface SessionTokenMap {
  [sessionId: string]: string;
}

function safeGet(key: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(key: string, value: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Quota exceeded / private browsing — silent skip.
  }
}

export function getSessionToken(sessionId: string): string | null {
  const raw = safeGet(SESSION_TOKENS_KEY);
  if (!raw) return null;
  try {
    const map: SessionTokenMap = JSON.parse(raw);
    return map[sessionId] ?? null;
  } catch {
    return null;
  }
}

export function setSessionToken(sessionId: string, token: string): void {
  const raw = safeGet(SESSION_TOKENS_KEY);
  let map: SessionTokenMap = {};
  if (raw) {
    try {
      map = JSON.parse(raw);
    } catch {
      map = {};
    }
  }
  map[sessionId] = token;
  safeSet(SESSION_TOKENS_KEY, JSON.stringify(map));
}

export function removeSessionToken(sessionId: string): void {
  const raw = safeGet(SESSION_TOKENS_KEY);
  if (!raw) return;
  try {
    const map: SessionTokenMap = JSON.parse(raw);
    delete map[sessionId];
    safeSet(SESSION_TOKENS_KEY, JSON.stringify(map));
  } catch {
    // ignore
  }
}

export function getRecentSessions(): RecentSessionMeta[] {
  const raw = safeGet(RECENT_SESSIONS_KEY);
  if (!raw) return [];
  try {
    const data = JSON.parse(raw);
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

export function addRecentSession(meta: RecentSessionMeta): void {
  const list = getRecentSessions();
  // Уже есть? — поднимаем наверх.
  const filtered = list.filter((s) => s.id !== meta.id);
  filtered.unshift(meta);
  // Keep max 10.
  safeSet(RECENT_SESSIONS_KEY, JSON.stringify(filtered.slice(0, 10)));
}
