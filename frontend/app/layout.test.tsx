import { describe, it, expect } from "vitest";
import RootLayout, { metadata } from "./layout";

describe("RootLayout", () => {
  it("exports metadata with reHome title and description", () => {
    expect(metadata.title).toMatch(/reHome/i);
    expect(metadata.description).toMatch(/reHome/i);
  });

  it("renders its children inside an html ru-locale shell", () => {
    const tree = RootLayout({ children: "child-content" }) as React.ReactElement<{
      lang: string;
      children: React.ReactNode;
    }>;
    expect(tree).toBeTruthy();
    expect(tree.props.lang).toBe("ru");
    expect(tree.type).toBe("html");
  });
});
