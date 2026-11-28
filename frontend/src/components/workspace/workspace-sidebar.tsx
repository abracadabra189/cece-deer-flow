"use client";

import { type Sidebar } from "@/components/ui/sidebar";
import { useThreadActivity } from "@/core/threads/activity";

import { HomeNavigation } from "./cecemate/home-navigation";
import { ThreadDeleteDialogProvider } from "./thread-delete-dialog";
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
        className="cece-home-sidebar"
        {...props}
      >
        <HomeNavigation />
      </WorkspaceSidebarFrame>
    </ThreadDeleteDialogProvider>
  );
}
