"use client";

import {
  BlocksIcon,
  BotIcon,
  CalendarClock,
  FilesIcon,
  SparklesIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  SidebarGroup,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { CeceMateBetaItem } from "@/components/workspace/cecemate/cecemate-beta-item";

export function WorkspaceNavChatList() {
  const pathname = usePathname();

  return (
    <>
      <SidebarGroup className="px-0 pt-0 pb-2">
        <SidebarMenu>
          <CeceMateBetaItem icon={CalendarClock} label="定时任务" />
          <SidebarMenuItem>
            <SidebarMenuButton
              isActive={pathname.startsWith("/workspace/skills")}
              asChild
              className="h-[30px] rounded-lg px-2.5 text-[13px] text-[#5a6478] data-[active=true]:bg-[#eef3ff] data-[active=true]:font-semibold data-[active=true]:text-[#2563eb]"
            >
              <Link href="/workspace/skills">
                <SparklesIcon />
                <span>技能</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <CeceMateBetaItem icon={BotIcon} label="专家" />
          <CeceMateBetaItem icon={BlocksIcon} label="MCP 服务" />
        </SidebarMenu>
      </SidebarGroup>
      <SidebarGroup className="mt-1 border-t border-[#e7ebf3] px-0 pt-1 pb-0">
        <SidebarMenu>
          <CeceMateBetaItem icon={FilesIcon} label="文件库" />
        </SidebarMenu>
      </SidebarGroup>
    </>
  );
}
