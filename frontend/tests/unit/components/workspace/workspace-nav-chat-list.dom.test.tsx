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

test("presents only the skills route in the CeCeMate navigation", () => {
  render(
    <SidebarProvider>
      <WorkspaceNavChatList />
    </SidebarProvider>,
  );

  for (const label of ["定时任务", "专家", "MCP 服务", "文件库"]) {
    expect(screen.queryByText(label, { exact: false })).toBeNull();
  }

  expect(screen.getByRole("link", { name: "技能" }).getAttribute("href")).toBe(
    "/workspace/skills",
  );
});
