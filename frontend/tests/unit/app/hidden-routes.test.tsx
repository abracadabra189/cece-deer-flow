import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import { beforeEach, describe, expect, it, rs } from "@rstest/core";

const notFound = rs.fn();

rs.mock("next/navigation", () => ({ notFound }));
rs.mock("@/core/agents", () => ({
  useAgentsApiEnabled: () => ({ enabled: true, isLoading: false }),
}));
rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({ t: { common: { loading: "加载中" } } }),
}));
rs.mock("@/components/workspace/agents/agents-feature-disabled", () => ({
  AgentsFeatureDisabled: () => null,
}));
rs.mock("@/core/threads/static-demo", () => ({
  DEMO_THREAD_IDS: ["demo-thread"],
  isDemoThreadId: () => true,
}));
rs.mock("@/components/workspace/chats/chat-page", () => ({
  __esModule: true,
  default: () => null,
}));
async function expectNotFound(route: () => unknown | Promise<unknown>) {
  await route();
  expect(notFound).toHaveBeenCalledTimes(1);
}

describe("hidden product routes", () => {
  beforeEach(() => notFound.mockClear());

  it("returns 404 for the custom Agent route tree", async () => {
    const { default: AgentsLayout } =
      await import("@/app/workspace/agents/layout");
    await expectNotFound(AgentsLayout);
  });

  it("returns 404 for the capability center", async () => {
    const { default: CapabilitiesPage } =
      await import("@/app/workspace/capabilities/page");
    await expectNotFound(CapabilitiesPage);
  });

  it("returns 404 for extension pages", async () => {
    const { default: ExtensionPage } =
      await import("@/app/workspace/extensions/[namespace]/[surface_id]/page");
    await expectNotFound(ExtensionPage);
  });

  it("returns 404 for public showcase pages", async () => {
    const { default: ShowcasePage } =
      await import("@/app/showcase/[thread_id]/page");
    await expectNotFound(ShowcasePage);
  });

  it.each([
    "src/app/workspace/usage/page.tsx",
    "src/app/blog/layout.tsx",
    "src/app/[lang]/docs/layout.tsx",
  ])("declares a 404 boundary for %s", async (routeFile) => {
    const source = await readFile(resolve(process.cwd(), routeFile), "utf8");

    expect(source).toContain('import { notFound } from "next/navigation"');
    expect(source).toContain("notFound();");
  });
});
