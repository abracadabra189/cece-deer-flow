"use client";

import { SettingsIcon } from "lucide-react";

import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";

import { useSettingsDialog } from "./settings";
import { useWorkspaceSidebarExpanded } from "./workspace-sidebar-frame";

function NavMenuButtonContent({ isSidebarOpen }: { isSidebarOpen: boolean }) {
  return isSidebarOpen ? (
    <div className="flex w-full items-center gap-2 text-left text-[12.5px] text-[#5a6478]">
      <SettingsIcon className="size-4 shrink-0" />
      <span>任务偏好配置</span>
      <small className="ml-auto text-[10px] font-normal text-[#8a94a6]">
        向平台补充说明
      </small>
    </div>
  ) : (
    <div className="flex size-full items-center justify-center">
      <SettingsIcon className="size-4 text-[#65718a]" />
    </div>
  );
}

export function WorkspaceNavMenu() {
  const { openSettings } = useSettingsDialog();
  const isSidebarOpen = useWorkspaceSidebarExpanded();

  return (
    <SidebarMenu className="w-full">
      <SidebarMenuItem>
        <SidebarMenuButton
          size="lg"
          className="h-9 rounded-lg px-1.5 hover:bg-[#f5f8ff] hover:text-[#2563eb]"
          onClick={() => openSettings("memory", { memoryOnly: true })}
        >
          <NavMenuButtonContent isSidebarOpen={isSidebarOpen} />
        </SidebarMenuButton>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
