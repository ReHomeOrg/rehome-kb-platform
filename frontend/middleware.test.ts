// @vitest-environment node
import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { middleware } from "@/middleware";

describe("middleware: /chat gate (чат только для залогиненных)", () => {
  it("редиректит анонима (нет kb_session) на /login чистым 307", () => {
    const req = new NextRequest(new URL("https://help.rehome.one/chat"));
    const res = middleware(req);

    expect(res.status).toBe(307);
    const location = res.headers.get("location") ?? "";
    expect(location).toContain("/login");
    expect(location).toContain("next=%2Fchat");
  });

  it("сохраняет next с подпутём сессии", () => {
    const req = new NextRequest(new URL("https://help.rehome.one/chat/abc-123"));
    const res = middleware(req);

    expect(res.status).toBe(307);
    expect(res.headers.get("location") ?? "").toContain("next=%2Fchat%2Fabc-123");
  });

  it("пропускает залогиненного (kb_session присутствует) — без редиректа", () => {
    const req = new NextRequest(new URL("https://help.rehome.one/chat"), {
      headers: { cookie: "kb_session=token" },
    });
    const res = middleware(req);

    expect(res.headers.get("location")).toBeNull();
    expect(res.headers.get("x-middleware-next")).toBe("1");
  });
});
