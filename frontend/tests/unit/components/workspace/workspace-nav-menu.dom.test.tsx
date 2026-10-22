import { afterEach, expect, test, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { SidebarProvider } from "@/components/ui/sidebar";
import { WorkspaceNavMenu } from "@/components/workspace/workspace-nav-menu";
import { enUS } from "@/core/i18n/locales/en-US";

rs.mock("@/components/workspace/settings", () => ({
  useSettingsDialog: () => ({ openSettings: rs.fn() }),
}));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));

afterEach(cleanup);

test("disables unavailable settings and more items", async () => {
  render(
    <SidebarProvider>
      <WorkspaceNavMenu />
    </SidebarProvider>,
  );

  fireEvent.pointerDown(
    await screen.findByRole("button", { name: /settings and more/i }),
    { button: 0, ctrlKey: false },
  );

  for (const label of [enUS.common.settings, "Visit the CECE website"]) {
    expect(screen.getByRole("menuitem", { name: label })).toBeDefined();
  }
  for (const label of [
    enUS.workspace.reportIssue,
    enUS.workspace.contactUs,
    "About CECE",
  ]) {
    const item = screen.getByRole("menuitem", { name: label });
    expect(item.getAttribute("data-disabled")).not.toBeNull();
    expect(item.closest("a")).toBeNull();
  }
  const reportIssueWrapper = screen.getByRole("menuitem", {
    name: enUS.workspace.reportIssue,
  }).parentElement!;
  fireEvent.pointerMove(reportIssueWrapper);
  fireEvent.mouseEnter(reportIssueWrapper);
  expect(
    (await screen.findAllByText("Feature not enabled")).length,
  ).toBeGreaterThan(0);
  expect(screen.queryByRole("menuitem", { name: /GitHub/i })).toBeNull();
  expect(
    screen
      .getByRole("menuitem", { name: "Visit the CECE website" })
      .closest("a")
      ?.getAttribute("href"),
  ).toBe("https://sh.ceis.cn/");
});
