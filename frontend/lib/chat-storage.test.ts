import { beforeEach, describe, expect, it } from "vitest";

import {
  addRecentSession,
  getRecentSessions,
  getSessionToken,
  removeSessionToken,
  setSessionToken,
} from "./chat-storage";

beforeEach(() => {
  window.localStorage.clear();
});

describe("chat-storage tokens", () => {
  it("getSessionToken returns null when none", () => {
    expect(getSessionToken("missing")).toBeNull();
  });

  it("set then get round-trip", () => {
    setSessionToken("s1", "tok-1");
    expect(getSessionToken("s1")).toBe("tok-1");
  });

  it("set overwrites existing", () => {
    setSessionToken("s1", "first");
    setSessionToken("s1", "second");
    expect(getSessionToken("s1")).toBe("second");
  });

  it("set multiple keys independent", () => {
    setSessionToken("a", "x");
    setSessionToken("b", "y");
    expect(getSessionToken("a")).toBe("x");
    expect(getSessionToken("b")).toBe("y");
  });

  it("remove deletes key", () => {
    setSessionToken("a", "x");
    removeSessionToken("a");
    expect(getSessionToken("a")).toBeNull();
  });

  it("malformed JSON in storage → returns null gracefully", () => {
    window.localStorage.setItem("rehome_chat_session_tokens", "{not-json");
    expect(getSessionToken("s")).toBeNull();
  });
});

describe("chat-storage recent sessions", () => {
  it("empty initially", () => {
    expect(getRecentSessions()).toEqual([]);
  });

  it("add → present in list", () => {
    addRecentSession({ id: "s1", created_at: "2026-05-12", scope: "guest" });
    const list = getRecentSessions();
    expect(list.length).toBe(1);
    expect(list[0].id).toBe("s1");
  });

  it("re-add same id moves to top", () => {
    addRecentSession({ id: "s1", created_at: "2026-05-12", scope: "guest" });
    addRecentSession({ id: "s2", created_at: "2026-05-12", scope: "guest" });
    addRecentSession({ id: "s1", created_at: "2026-05-13", scope: "guest" });
    const list = getRecentSessions();
    expect(list[0].id).toBe("s1");
    expect(list[1].id).toBe("s2");
    expect(list.length).toBe(2);
  });

  it("cap at 10 entries", () => {
    for (let i = 0; i < 15; i += 1) {
      addRecentSession({
        id: `s${i}`,
        created_at: "2026-05-12",
        scope: "guest",
      });
    }
    expect(getRecentSessions().length).toBe(10);
  });

  it("malformed JSON → empty array", () => {
    window.localStorage.setItem("rehome_chat_recent_sessions", "garbage");
    expect(getRecentSessions()).toEqual([]);
  });
});
