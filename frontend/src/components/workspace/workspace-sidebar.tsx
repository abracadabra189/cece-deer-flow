"use client";

import {
  type Sidebar,
  SidebarHeader,
  SidebarContent,
  SidebarFooter,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";
import { useThreadActivity } from "@/core/threads/activity";

import { RecentChatList } from "./recent-chat-list";
import { ThreadDeleteDialogProvider } from "./thread-delete-dialog";
import { WorkspaceHeader } from "./workspace-header";
import { WorkspaceNavChatList } from "./workspace-nav-chat-list";
import { WorkspaceNavMenu } from "./workspace-nav-menu";
import { WorkspaceSidebarFrame } from "./workspace-sidebar-frame";

export function WorkspaceSidebar({
  ...props
}: React.ComponentProps<typeof Sidebar>) {
  // One activity poll per workspace (off unless the Gateway offers it): new
  // and changed server-created threads reach the thread lists without a
  // reload, and a read on another device clears their dots here.
  useThreadActivity();
  return (
    <ThreadDeleteDialogProvider>
      <WorkspaceSidebarFrame
        variant="sidebar"
        collapsible="icon"
        className="border-[#e7ebf3] [--sidebar-width:248px]"
        {...props}
      >
        <WorkspaceSidebarContents />
      </WorkspaceSidebarFrame>
    </ThreadDeleteDialogProvider>
  );
}

function WorkspaceSidebarContents() {
  const { isMobile } = useSidebar();
  return (
    <>
      <SidebarHeader className="gap-0 p-0">
        <WorkspaceHeader />
      </SidebarHeader>
      <SidebarContent className="gap-0 px-2 pt-0">
        <WorkspaceNavChatList />
        <RecentChatList />
      </SidebarContent>
      <SidebarFooter className="border-sidebar-border border-t p-2">
        <WorkspaceNavMenu />
      </SidebarFooter>
      {!isMobile && <SidebarRail />}
    </>
  );
}
