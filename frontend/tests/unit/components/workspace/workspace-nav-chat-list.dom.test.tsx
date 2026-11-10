import { afterEach, expect, test, rs } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { SidebarProvider } from "@/components/ui/sidebar";
import { WorkspaceNavChatList } from "@/components/workspace/workspace-nav-chat-list";

rs.mock("next/navigation", () => ({
  usePathname: () => "/workspace/chats/new",
}));
rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      sidebar: {
        chats: "对话",
        agents: "智能体",
        scheduledTasks: "定时任务",
        agentsDisabledTooltip: "暂不可用",
      },
      capabilities: { title: "能力中心" },
      usage: { title: "用量" },
    },
  }),
}));
rs.mock("@/core/agents", () => ({
  useAgentsApiEnabled: () => ({ enabled: false }),
}));

afterEach(cleanup);

test("presents CeCeMate navigation with only the skills route and inert Beta entries", () => {
  render(
    <SidebarProvider>
      <WorkspaceNavChatList />
    </SidebarProvider>,
  );

  for (const label of [
    "定时任务 Beta",
    "专家 Beta",
    "MCP 服务 Beta",
    "文件库 Beta",
  ]) {
    const button = screen.getByRole("button", { name: label });
    expect(button.getAttribute("aria-disabled")).toBe("true");
    expect(button.querySelector("a")).toBeNull();
  }

  expect(screen.getByRole("link", { name: "技能" }).getAttribute("href")).toBe(
    "/workspace/skills",
  );
});
