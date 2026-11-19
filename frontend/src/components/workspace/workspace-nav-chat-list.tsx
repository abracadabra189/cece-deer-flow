"use client";

import { SparklesIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  SidebarGroup,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";

export function WorkspaceNavChatList() {
  const pathname = usePathname();

  return (
    <>
      <SidebarGroup className="px-0 pt-0 pb-2">
        <SidebarMenu>
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
        </SidebarMenu>
      </SidebarGroup>
    </>
  );
}
