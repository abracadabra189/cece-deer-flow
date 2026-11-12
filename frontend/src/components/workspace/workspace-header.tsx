"use client";

import { MessageSquarePlus } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useSidebar } from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";

import { CeceMateBrand, CeceMateLogo } from "./cecemate/cecemate-brand";
import { useWorkspaceSidebarExpanded } from "./workspace-sidebar-frame";
import { WorkspaceSidebarTrigger } from "./workspace-sidebar-trigger";

export function WorkspaceHeader({ className }: { className?: string }) {
  const { isMobile } = useSidebar();
  const isSidebarOpen = useWorkspaceSidebarExpanded();
  const pathname = usePathname();
  return (
    <>
      <div
        className={cn(
          "group/workspace-header border-sidebar-border flex h-[52px] flex-col justify-center border-b px-[14px]",
          className,
        )}
      >
        {!isSidebarOpen ? (
          <div className="group-has-data-[collapsible=icon]/sidebar-wrapper:-translate-y flex w-full items-center justify-center">
            <CeceMateLogo
              className={cn(
                "animate-in fade-in zoom-in-75 size-6 origin-center duration-200 ease-out group-hover/workspace-header:hidden",
                isMobile && "hidden",
              )}
            />
            <WorkspaceSidebarTrigger
              className={cn(
                "pl-2",
                !isMobile && "hidden group-hover/workspace-header:block",
              )}
            />
          </div>
        ) : (
          <div className="flex items-center justify-between gap-2">
            <CeceMateBrand />
            <WorkspaceSidebarTrigger />
          </div>
        )}
      </div>
      <div className="mx-3 mt-3 mb-2 h-9 group-data-[collapsible=icon]:mx-auto group-data-[collapsible=icon]:my-3 group-data-[collapsible=icon]:size-8">
        <Link
          aria-current={
            pathname === "/workspace/chats/new" ? "page" : undefined
          }
          className="flex size-full items-center justify-center gap-1.5 rounded-[9px] bg-linear-to-br from-[#2563eb] to-[#7b5cff] text-[13.5px] font-semibold text-white shadow-[0_4px_12px_rgb(57_110_255_/_0.32)] transition-[filter] group-data-[collapsible=icon]:rounded-lg hover:text-white hover:brightness-105"
          href="/workspace/chats/new"
        >
          <MessageSquarePlus className="size-4" />
          <span className="group-data-[collapsible=icon]:hidden">新建任务</span>
        </Link>
      </div>
    </>
  );
}
