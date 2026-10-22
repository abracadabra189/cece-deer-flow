import { afterEach, expect, test, rs } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { SidebarProvider } from "@/components/ui/sidebar";
import { WorkspaceNavChatList } from "@/components/workspace/workspace-nav-chat-list";
import { enUS } from "@/core/i18n/locales/en-US";

rs.mock("next/navigation", () => ({
  usePathname: () => "/workspace/chats/new",
}));
rs.mock("@/core/agents", () => ({
  useAgentsApiEnabled: () => ({ enabled: false }),
}));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));

afterEach(cleanup);

test("keeps unavailable workspace destinations visible but prevents navigation", () => {
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
});
