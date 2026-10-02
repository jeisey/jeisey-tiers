import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BrandLogo } from "../src/app/Masthead";
import { homeHref } from "../src/app/useAppState";

describe("the logo links home", () => {
  it("resolves home from the configured base, with no query", () => {
    expect(homeHref("/")).toBe("/");
    expect(homeHref("/jeisey-tiers/")).toBe("/jeisey-tiers/");
    // A base written without its trailing slash still names the directory, not a file.
    expect(homeHref("/jeisey-tiers")).toBe("/jeisey-tiers/");
  });

  it("is a real link inside the page's one h1, named for where it goes", () => {
    render(<BrandLogo />);
    const link = screen.getByRole("link", { name: "Jeisey Tiers home" });
    expect(link.tagName).toBe("A");
    expect(link.getAttribute("href")).toBe(import.meta.env.BASE_URL);
    expect(link.getAttribute("href")).not.toContain("?");
    expect(screen.getByRole("heading", { level: 1 }).contains(link)).toBe(true);
    expect(screen.getByRole("img", { name: "Jeisey Tiers" })).toBeTruthy();
  });
});
