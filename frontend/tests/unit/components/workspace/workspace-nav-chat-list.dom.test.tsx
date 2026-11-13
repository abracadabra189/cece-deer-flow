import { afterEach, expect, test, rs } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { SidebarProvider } from "@/components/ui/sidebar";
import { WorkspaceHeader } from "@/components/workspace/workspace-container";
import { WorkspaceNavChatList } from "@/components/workspace/workspace-nav-chat-list";
import { enUS } from "@/core/i18n/locales/en-US";

rs.mock("next/navigation", () => ({
  usePathname: () => "/workspace/chats/new",
}));
rs.mock("@/core/agents", () => ({
  useAgentsApiEnabled: () => ({ enabled: false }),
}));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));
rs.mock("@/components/workspace/workspace-sidebar-trigger", () => ({
  WorkspaceSidebarTrigger: () => null,
}));

afterEach(cleanup);

test("keeps CECE-disabled destinations unavailable but exposes token usage", () => {
  render(
    <SidebarProvider>
      <WorkspaceNavChatList />
    </SidebarProvider>,
  );

  for (const label of [
    enUS.sidebar.agents,
    enUS.sidebar.scheduledTasks,
    enUS.capabilities.title,
  ]) {
    const button = screen.getByRole("button", { name: label });
    expect(button.getAttribute("aria-disabled")).toBe("true");
    expect(button.querySelector("a")).toBeNull();
  }

  expect(
    screen.getByRole("link", { name: enUS.usage.title }).getAttribute("href"),
  ).toBe("/workspace/usage");
});

test("does not expose the upstream GitHub link in the workspace header", () => {
  const { container } = render(<WorkspaceHeader />);

  expect(
    container.querySelector('a[href="https://github.com/bytedance/deer-flow"]'),
  ).toBeNull();
});
