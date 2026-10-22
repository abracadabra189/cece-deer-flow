"use client";

import {
  BugIcon,
  ChevronsUpDown,
  GlobeIcon,
  InfoIcon,
  MailIcon,
  Settings2Icon,
  SettingsIcon,
} from "lucide-react";
import { useEffect, useState } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { Tooltip } from "@/components/workspace/tooltip";
import { useI18n } from "@/core/i18n/hooks";

import { useSettingsDialog } from "./settings";
import { useWorkspaceSidebarExpanded } from "./workspace-sidebar-frame";

function NavMenuButtonContent({
  isSidebarOpen,
  t,
}: {
  isSidebarOpen: boolean;
  t: ReturnType<typeof useI18n>["t"];
}) {
  return isSidebarOpen ? (
    <div className="text-muted-foreground flex w-full items-center gap-2 text-left text-sm">
      <SettingsIcon className="size-4" />
      <span>{t.workspace.settingsAndMore}</span>
      <ChevronsUpDown className="text-muted-foreground ml-auto size-4" />
    </div>
  ) : (
    <div className="flex size-full items-center justify-center">
      <SettingsIcon className="text-muted-foreground size-4" />
    </div>
  );
}

function UnavailableMenuItem({
  icon: Icon,
  label,
  tooltip,
}: {
  icon: typeof BugIcon;
  label: string;
  tooltip: string;
}) {
  return (
    <Tooltip content={tooltip}>
      <span className="block cursor-not-allowed">
        <DropdownMenuItem disabled>
          <Icon />
          {label}
        </DropdownMenuItem>
      </span>
    </Tooltip>
  );
}

export function WorkspaceNavMenu() {
  const { openSettings } = useSettingsDialog();
  const [mounted, setMounted] = useState(false);
  const isSidebarOpen = useWorkspaceSidebarExpanded();
  const { t } = useI18n();

  useEffect(() => {
    setMounted(true);
  }, []);

  return (
    <>
      <SidebarMenu className="w-full">
        <SidebarMenuItem>
          {mounted ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <SidebarMenuButton
                  size="lg"
                  className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
                >
                  <NavMenuButtonContent isSidebarOpen={isSidebarOpen} t={t} />
                </SidebarMenuButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                className="w-(--radix-dropdown-menu-trigger-width) min-w-56 rounded-lg"
                align="end"
                sideOffset={4}
              >
                <DropdownMenuGroup>
                  <DropdownMenuItem
                    onClick={() => {
                      openSettings("appearance");
                    }}
                  >
                    <Settings2Icon />
                    {t.common.settings}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <a
                    href="https://sh.ceis.cn/"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <DropdownMenuItem>
                      <GlobeIcon />
                      {t.workspace.officialWebsite}
                    </DropdownMenuItem>
                  </a>
                  <DropdownMenuSeparator />
                  <UnavailableMenuItem
                    icon={BugIcon}
                    label={t.workspace.reportIssue}
                    tooltip={t.sidebar.agentsDisabledTooltip}
                  />
                  <UnavailableMenuItem
                    icon={MailIcon}
                    label={t.workspace.contactUs}
                    tooltip={t.sidebar.agentsDisabledTooltip}
                  />
                  <DropdownMenuSeparator />
                  <UnavailableMenuItem
                    icon={InfoIcon}
                    label={t.workspace.about}
                    tooltip={t.sidebar.agentsDisabledTooltip}
                  />
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <SidebarMenuButton size="lg" className="pointer-events-none">
              <NavMenuButtonContent isSidebarOpen={isSidebarOpen} t={t} />
            </SidebarMenuButton>
          )}
        </SidebarMenuItem>
      </SidebarMenu>
    </>
  );
}
