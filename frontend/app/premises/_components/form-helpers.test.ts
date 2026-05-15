import { describe, expect, it } from "vitest";

import { jsonToString, parseJsonOrNull } from "./form-helpers";

describe("jsonToString", () => {
  it("returns empty string для null", () => {
    expect(jsonToString(null)).toBe("");
  });

  it("returns empty string для undefined", () => {
    expect(jsonToString(undefined)).toBe("");
  });

  it("returns empty string для пустого объекта", () => {
    expect(jsonToString({})).toBe("");
  });

  it("returns pretty-printed JSON для непустого объекта", () => {
    expect(jsonToString({ name: "Test", value: 42 })).toBe(
      '{\n  "name": "Test",\n  "value": 42\n}',
    );
  });

  it("сериализует nested структуры", () => {
    const out = jsonToString({ owner: { name: "X" } });
    expect(out).toContain('"owner"');
    expect(out).toContain('"name": "X"');
  });
});

describe("parseJsonOrNull", () => {
  it("returns null для пустой строки", () => {
    expect(parseJsonOrNull("")).toBeNull();
  });

  it("returns null для whitespace-only string", () => {
    expect(parseJsonOrNull("   \n\t  ")).toBeNull();
  });

  it("parses valid JSON object", () => {
    expect(parseJsonOrNull('{"a": 1}')).toEqual({ a: 1 });
  });

  it("parses empty JSON object {}", () => {
    expect(parseJsonOrNull("{}")).toEqual({});
  });

  it("returns error string для array (must be object)", () => {
    expect(parseJsonOrNull("[1, 2, 3]")).toBe("must be JSON object");
  });

  it("returns error string для primitive number", () => {
    expect(parseJsonOrNull("42")).toBe("must be JSON object");
  });

  it("returns error string для primitive string", () => {
    expect(parseJsonOrNull('"just a string"')).toBe("must be JSON object");
  });

  it("returns error string для malformed JSON", () => {
    expect(parseJsonOrNull("{ unclosed")).toBe("invalid JSON");
  });

  it("trims whitespace перед parse", () => {
    expect(parseJsonOrNull('   {"x": 1}   ')).toEqual({ x: 1 });
  });

  it("JSON null parsed как null (валидно)", () => {
    expect(parseJsonOrNull("null")).toBeNull();
  });
});
