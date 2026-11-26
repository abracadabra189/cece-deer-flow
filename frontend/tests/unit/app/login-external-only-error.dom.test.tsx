import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import LoginPage from "@/app/(auth)/login/page";
import type * as AuthProviderModule from "@/core/auth/AuthProvider";
import { useAuth } from "@/core/auth/AuthProvider";
import type * as Setup from "@/core/auth/setup";
import { enUS } from "@/core/i18n/locales/en-US";

// The external hand-off sends failures back to /login?error=external_login_failed.
// With password sign-in closed there is no form left to carry that message, so the
// notice has to — otherwise an expired or replayed ticket looks like a blank page.
rs.mock("@/core/auth/AuthProvider", () => ({
  ...(rs.requireActual<typeof AuthProviderModule>(
    "@/core/auth/AuthProvider",
  ) as object),
  useAuth: rs.fn(),
}));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));
rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn() }),
  useSearchParams: () =>
    new URLSearchParams({ error: "external_login_failed" }),
}));
rs.mock("next-themes", () => ({
  useTheme: () => ({ theme: "light", resolvedTheme: "light" }),
}));
rs.mock("@/components/ui/flickering-grid", () => ({
  FlickeringGrid: () => null,
}));
rs.mock("@/core/auth/setup", () => ({
  ...(rs.requireActual<typeof Setup>("@/core/auth/setup") as object),
  fetchSetupStatus: rs.fn(async () => ({
    needs_setup: false,
    registration_enabled: false,
    password_login_enabled: false,
  })),
}));

beforeEach(() => {
  rs.mocked(useAuth).mockReturnValue({
    isAuthenticated: false,
  } as ReturnType<typeof useAuth>);
  globalThis.fetch = rs.fn(
    async () =>
      new Response(JSON.stringify({ providers: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
  ) as unknown as typeof globalThis.fetch;
});
afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

test("a failed external hand-off states its reason with the form hidden", async () => {
  render(<LoginPage />);

  expect(
    await screen.findByText(enUS.login.errors.external_login_failed),
  ).toBeTruthy();
  expect(screen.getByText(enUS.login.externalOnlyTitle)).toBeTruthy();
  expect(screen.queryByRole("button", { name: enUS.login.signIn })).toBeNull();
});
