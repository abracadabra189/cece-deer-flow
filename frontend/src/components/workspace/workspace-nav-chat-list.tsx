"use client";

import {
  BotIcon,
  CalendarClock,
  MessagesSquare,
  BlocksIcon,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  SidebarGroup,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useAgentsApiEnabled } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";

export function WorkspaceNavChatList() {
  const { t } = useI18n();
  const pathname = usePathname();
  const { enabled: agentsEnabled } = useAgentsApiEnabled();
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
        <SidebarMenuItem>
          {agentsEnabled ? (
            <SidebarMenuButton
              isActive={pathname.startsWith("/workspace/agents")}
              asChild
            >
              <Link className="text-muted-foreground" href="/workspace/agents">
                <BotIcon />
                <span>{t.sidebar.agents}</span>
              </Link>
            </SidebarMenuButton>
          ) : (
            <DisabledNavigationItem
              icon={BotIcon}
              label={t.sidebar.agents}
              reason={t.sidebar.agentsDisabledTooltip}
              reasonId="agents-disabled-reason"
            />
          )}
        </SidebarMenuItem>
        <SidebarMenuItem>
          <DisabledNavigationItem
            icon={CalendarClock}
            label={t.sidebar.scheduledTasks}
            reason={t.sidebar.agentsDisabledTooltip}
            reasonId="scheduled-tasks-disabled-reason"
          />
        </SidebarMenuItem>
        <SidebarMenuItem>
          <DisabledNavigationItem
            icon={BlocksIcon}
            label={t.capabilities.title}
            reason={t.sidebar.agentsDisabledTooltip}
            reasonId="capabilities-disabled-reason"
          />
        </SidebarMenuItem>
      </SidebarMenu>
    </SidebarGroup>
  );
}

function DisabledNavigationItem({
  icon: Icon,
  label,
  reason,
  reasonId,
}: {
  icon: LucideIcon;
  label: string;
  reason: string;
  reasonId: string;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        {/* Keep the wrapper interactive so disabled navigation still explains
            itself on hover. The button remains keyboard-focusable and exposes
            the same reason through aria-describedby. */}
        <span className="block w-full cursor-not-allowed">
          <SidebarMenuButton
            className="text-muted-foreground/50"
            aria-disabled
            aria-describedby={reasonId}
          >
            <Icon />
            <span>{label}</span>
          </SidebarMenuButton>
          <span id={reasonId} className="sr-only">
            {reason}
          </span>
        </span>
      </TooltipTrigger>
      <TooltipContent side="right">{reason}</TooltipContent>
    </Tooltip>
  );
}
