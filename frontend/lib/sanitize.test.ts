import { describe, expect, it } from "vitest";

import { sanitizeSearchSnippet } from "./sanitize";

describe("sanitizeSearchSnippet", () => {
  it("preserves <b> tag (ts_headline whitelist)", () => {
    expect(sanitizeSearchSnippet("hello <b>world</b>")).toBe(
      "hello <b>world</b>",
    );
  });

  it("passes plain text through", () => {
    expect(sanitizeSearchSnippet("just plain text")).toBe("just plain text");
  });

  it("strips <script> entirely (XSS prevention)", () => {
    const out = sanitizeSearchSnippet("<script>alert(1)</script>");
    expect(out).not.toContain("script");
    expect(out).not.toContain("alert");
  });

  it("strips <a> tag but keeps inner text", () => {
    expect(sanitizeSearchSnippet('text <a href="evil.com">link</a>')).toBe(
      "text link",
    );
  });

  it("strips <i> (non-whitelisted даже если выглядит безобидно)", () => {
    expect(sanitizeSearchSnippet("a <i>b</i> c")).toBe("a b c");
  });

  it("strips onerror attribute on <b>", () => {
    const out = sanitizeSearchSnippet('<b onerror="alert(1)">x</b>');
    expect(out).not.toContain("onerror");
    expect(out).toContain("<b>x</b>");
  });

  it("preserves Cyrillic content inside <b>", () => {
    expect(sanitizeSearchSnippet("найдено <b>совпадение</b>")).toBe(
      "найдено <b>совпадение</b>",
    );
  });

  it("empty string returns empty", () => {
    expect(sanitizeSearchSnippet("")).toBe("");
  });
});
