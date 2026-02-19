import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ContactForm } from "@/components/contact/ContactForm";
import { vi } from "vitest";

describe("ContactForm", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockImplementation(
      async () =>
        ({
          ok: true,
          json: vi.fn().mockResolvedValue({}),
        }) as unknown as Response,
    );
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("requires a message and validates email when provided", async () => {
    render(<ContactForm />);

    fireEvent.click(screen.getByRole("button", { name: /send message/i }));
    expect(await screen.findByText(/Please include a short note/i)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/How can we help?/i), { target: { value: "Hi" } });
    fireEvent.change(screen.getByLabelText(/Email/i), { target: { value: "not-an-email" } });
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));

    expect(await screen.findByText(/valid email address or leave it blank/i)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("submits with a turnstile token when provided", async () => {
    const renderMock = vi.fn((_, options: any) => {
      options.callback?.("turnstile-token");
      return "widget-id";
    });
    const resetMock = vi.fn();
    const script = document.createElement("script");
    script.id = "cf-turnstile";
    document.head.appendChild(script);
    vi.stubGlobal("turnstile", { render: renderMock, reset: resetMock });

    render(<ContactForm siteKey="site-key" />);
    await waitFor(() => expect(renderMock).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText(/Name/i), { target: { value: "Alice" } });
    fireEvent.change(screen.getByLabelText(/How can we help?/i), { target: { value: "Hello" } });
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [, options] = fetchMock.mock.calls[0];
    const body = JSON.parse((options as RequestInit).body as string);
    expect(body.turnstileToken).toBe("turnstile-token");
  });
});
