import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import MessageInput from "./message-input";

describe("MessageInput", () => {
  it("disables submit button on empty input", () => {
    render(<MessageInput onSend={vi.fn()} />);
    const btn = screen.getByText("Отправить") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("enables submit when text typed", () => {
    render(<MessageInput onSend={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText(/вопрос/i), {
      target: { value: "hi" },
    });
    expect((screen.getByText("Отправить") as HTMLButtonElement).disabled).toBe(
      false,
    );
  });

  it("calls onSend with trimmed content + clears input", async () => {
    const onSend = vi.fn().mockResolvedValue(undefined);
    render(<MessageInput onSend={onSend} />);
    const input = screen.getByPlaceholderText(/вопрос/i) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "  hello  " } });
    fireEvent.click(screen.getByText("Отправить"));
    await waitFor(() => expect(onSend).toHaveBeenCalledWith("hello"));
    await waitFor(() => expect(input.value).toBe(""));
  });

  it("disabled prop prevents submit", () => {
    const onSend = vi.fn();
    render(<MessageInput onSend={onSend} disabled />);
    const input = screen.getByPlaceholderText(/вопрос/i) as HTMLInputElement;
    expect(input.disabled).toBe(true);
  });
});
