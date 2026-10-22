"use client";

import {
  BotIcon,
  CalendarClock,
  MessagesSquare,
  BlocksIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  SidebarGroup,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { Tooltip } from "@/components/workspace/tooltip";
import { useI18n } from "@/core/i18n/hooks";

function UnavailableWorkspaceNavItem({
  icon: Icon,
  label,
  tooltip,
}: {
  icon: typeof BotIcon;
  label: string;
  tooltip: string;
}) {
  return (
    <SidebarMenuItem>
      <Tooltip content={tooltip}>
        <span className="block cursor-not-allowed">
          <SidebarMenuButton aria-disabled="true" disabled>
            <Icon />
            <span>{label}</span>
          </SidebarMenuButton>
        </span>
      </Tooltip>
    </SidebarMenuItem>
  );
}

export function WorkspaceNavChatList() {
  const { t } = useI18n();
  const pathname = usePathname();
  return (
    <SidebarGroup className="pt-1">
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton isActive={pathname === "/workspace/chats"} asChild>
            <Link className="text-muted-foreground" href="/workspace/chats">
              <MessagesSquare />
              <span>{t.sidebar.chats}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <UnavailableWorkspaceNavItem
          icon={BotIcon}
          label={t.sidebar.agents}
          tooltip={t.sidebar.agentsDisabledTooltip}
        />
        <UnavailableWorkspaceNavItem
          icon={CalendarClock}
          label={t.sidebar.scheduledTasks}
          tooltip={t.sidebar.agentsDisabledTooltip}
        />
        <UnavailableWorkspaceNavItem
          icon={BlocksIcon}
          label={t.capabilities.title}
          tooltip={t.sidebar.agentsDisabledTooltip}
        />
      </SidebarMenu>
    </SidebarGroup>
  );
}
