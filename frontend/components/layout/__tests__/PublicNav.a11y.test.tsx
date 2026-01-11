import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PublicNav } from "../PublicNav";

describe("PublicNav accessibility", () => {
  it("sets aria-expanded and controls mobile nav", async () => {
    render(<PublicNav />);
    const button = screen.getByRole("button", { name: /menu/i });
    expect(button).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("navigation", { name: /public-mobile-nav/i })).toBeInTheDocument();
  });

  it("traps focus within the mobile menu and closes on Escape", async () => {
    render(<PublicNav />);
    const button = screen.getByRole("button", { name: /menu/i });
    await userEvent.click(button);
    const firstLink = screen.getByRole("link", { name: /Search/i });
    expect(firstLink).toHaveFocus();

    // Shift+Tab at first element should wrap to last link
    await userEvent.keyboard("{Shift>}{Tab}{/Shift}");
    const lastLink = screen.getByRole("link", { name: /Request access/i });
    expect(lastLink).toHaveFocus();

    // Escape closes and returns focus to trigger
    await userEvent.keyboard("{Escape}");
    expect(button).toHaveFocus();
    expect(button).toHaveAttribute("aria-expanded", "false");
  });
});
