import { afterEach, expect, rs, test } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { SidebarProvider } from "@/components/ui/sidebar";
import { WorkspaceNavMenu } from "@/components/workspace/workspace-nav-menu";

const settingsState = rs.hoisted(() => ({ openSettings: rs.fn() }));

rs.mock("@/components/workspace/settings", () => ({
  useSettingsDialog: () => settingsState,
}));

afterEach(cleanup);
afterEach(() => {
  rs.clearAllMocks();
});

test("opens the memory view directly from task preferences", async () => {
  render(
    <SidebarProvider>
      <WorkspaceNavMenu />
    </SidebarProvider>,
  );

  fireEvent.click(
    await screen.findByRole("button", {
      name: "任务偏好配置 向平台补充说明",
    }),
  );

  expect(settingsState.openSettings).toHaveBeenCalledWith("memory", {
    memoryOnly: true,
  });
  expect(screen.queryByRole("menu")).toBeNull();
});
