"use client";

import {
  BotIcon,
  CalendarClock,
  MessagesSquare,
  BlocksIcon,
  ChartColumn,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useId } from "react";

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

function UnavailableWorkspaceNavItem({
  icon: Icon,
  label,
  tooltip,
}: {
  icon: typeof BotIcon;
  label: string;
  tooltip: string;
}) {
  const reasonId = useId();

  return (
    <SidebarMenuItem>
      <Tooltip>
        <TooltipTrigger asChild>
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
              {tooltip}
            </span>
          </span>
        </TooltipTrigger>
        <TooltipContent side="right">{tooltip}</TooltipContent>
      </Tooltip>
    </SidebarMenuItem>
  );
}

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
            <Tooltip>
              <TooltipTrigger asChild>
                {/* cursor-not-allowed lives on the span (the element that
                    still receives pointer events), not the inert button. */}
                <span className="block w-full cursor-not-allowed">
                  <SidebarMenuButton
                    className="text-muted-foreground/50"
                    aria-disabled
                    aria-describedby="agents-disabled-reason"
                  >
                    <BotIcon />
                    <span>{t.sidebar.agents}</span>
                  </SidebarMenuButton>
                  <span id="agents-disabled-reason" className="sr-only">
                    {t.sidebar.agentsDisabledTooltip}
                  </span>
                </span>
              </TooltipTrigger>
              <TooltipContent side="right">
                {t.sidebar.agentsDisabledTooltip}
              </TooltipContent>
            </Tooltip>
          )}
        </SidebarMenuItem>
        <UnavailableWorkspaceNavItem
          icon={CalendarClock}
          label={t.sidebar.scheduledTasks}
          tooltip={t.sidebar.agentsDisabledTooltip}
        />
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/usage")}
            asChild
          >
            <Link className="text-muted-foreground" href="/workspace/usage">
              <ChartColumn />
              <span>{t.usage.title}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <UnavailableWorkspaceNavItem
          icon={BlocksIcon}
          label={t.capabilities.title}
          tooltip={t.sidebar.agentsDisabledTooltip}
        />
      </SidebarMenu>
    </SidebarGroup>
  );
}
