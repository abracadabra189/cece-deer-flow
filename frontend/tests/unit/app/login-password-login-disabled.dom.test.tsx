import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

import LoginPage from "@/app/(auth)/login/page";
import type * as AuthProviderModule from "@/core/auth/AuthProvider";
import { useAuth } from "@/core/auth/AuthProvider";
import type * as Setup from "@/core/auth/setup";
import { enUS } from "@/core/i18n/locales/en-US";

// Keep the real setup module (the absence rule under test lives in
// isPasswordLoginDisabled); override only the probe result.
rs.mock("@/core/auth/AuthProvider", () => ({
  ...(rs.requireActual<typeof AuthProviderModule>(
    "@/core/auth/AuthProvider",
  ) as object),
  useAuth: rs.fn(),
}));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));
rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
rs.mock("next-themes", () => ({
  useTheme: () => ({ theme: "light", resolvedTheme: "light" }),
}));
rs.mock("@/components/ui/flickering-grid", () => ({
  FlickeringGrid: () => null,
}));

let setupStatus: Setup.SetupStatusResponse = {
  needs_setup: false,
  registration_enabled: true,
  password_login_enabled: false,
};
rs.mock("@/core/auth/setup", () => ({
  ...(rs.requireActual<typeof Setup>("@/core/auth/setup") as object),
  fetchSetupStatus: rs.fn(async () => setupStatus),
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

test("a closed password gate hides the form and says where to sign in", async () => {
  setupStatus = {
    needs_setup: false,
    registration_enabled: true,
    password_login_enabled: false,
  };
  render(<LoginPage />);

  expect(await screen.findByText(enUS.login.externalOnlyTitle)).toBeTruthy();
  expect(screen.queryByLabelText(enUS.login.email)).toBeNull();
  expect(screen.queryByLabelText(enUS.login.password)).toBeNull();
  expect(screen.queryByRole("button", { name: enUS.login.signIn })).toBeNull();
  // Sign-up is meaningless once password sign-in is closed, even while the
  // Gateway still reports registration as open.
  expect(
    screen.queryByRole("button", { name: enUS.login.noAccountSignUp }),
  ).toBeNull();
});

test("an open password gate still renders the form", async () => {
  setupStatus = {
    needs_setup: false,
    registration_enabled: true,
    password_login_enabled: true,
  };
  render(<LoginPage />);

  await waitFor(() => screen.getByRole("button", { name: enUS.login.signIn }));
  expect(screen.queryByText(enUS.login.externalOnlyTitle)).toBeNull();
});

test("a Gateway that predates the flag keeps the form", async () => {
  // Absent must not hide sign-in: only an explicit false closes it, so an
  // older Gateway cannot lock everybody out of a password deployment.
  setupStatus = { needs_setup: false, registration_enabled: true };
  render(<LoginPage />);

  await waitFor(() => screen.getByRole("button", { name: enUS.login.signIn }));
  expect(screen.queryByText(enUS.login.externalOnlyTitle)).toBeNull();
});
