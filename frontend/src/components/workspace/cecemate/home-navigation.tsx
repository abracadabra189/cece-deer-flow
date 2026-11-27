"use client";

import Image from "next/image";
import Link from "next/link";

import { SidebarContent, useSidebar } from "@/components/ui/sidebar";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

import { RecentChatList } from "../recent-chat-list";
import { useSettingsDialog } from "../settings";
import { useWorkspaceSidebarExpanded } from "../workspace-sidebar-frame";

const assets = "/images/cecemate-home/";
export function HomeNavigation() {
  const expanded = useWorkspaceSidebarExpanded();
  const { openSettings } = useSettingsDialog();
  const { isMobile, setOpenMobile } = useSidebar();
  const closeDrawer = () => {
    if (isMobile) setOpenMobile(false);
  };
  return (
    <nav className="home-nav" data-expanded={expanded} aria-label="任务导航">
      <Link
        className="home-new-task"
        href="/workspace/chats/new"
        aria-label="开启新任务"
        title="开启新任务"
        onClick={closeDrawer}
      >
        <Image
          src={assets + "new-task-icon.svg"}
          alt=""
          width={20}
          height={20}
        />
        {expanded && (
          <Image
            src={assets + "new-task-label.svg"}
            alt=""
            width={80}
            height={22}
          />
        )}
      </Link>
      {[
        { label: "技能", path: "/workspace/skills", icon: "nav-skills" },
        { label: "MCP服务", path: "/workspace/mcp", icon: "nav-mcp" },
      ].map(({ label, path, icon }) => {
        const navigationLink = (
          <Link
            className="home-nav-link"
            href={path}
            aria-label={label}
            onClick={closeDrawer}
          >
            <span aria-hidden="true" className="home-nav-icon-shell">
              <span
                className="home-nav-icon"
                style={{
                  WebkitMaskImage: `url(${assets}${icon}.svg)`,
                  maskImage: `url(${assets}${icon}.svg)`,
                }}
              />
            </span>
            {expanded && label}
          </Link>
        );
        return (
          <Tooltip key={path} open={expanded ? false : undefined}>
            <TooltipTrigger asChild>{navigationLink}</TooltipTrigger>
            {!expanded && (
              <TooltipContent
                className="home-nav-tooltip"
                side="right"
                sideOffset={8}
              >
                {label}
              </TooltipContent>
            )}
          </Tooltip>
        );
      })}
      {expanded && (
        <SidebarContent className="min-h-0 gap-0 overflow-y-auto">
          <RecentChatList home />
        </SidebarContent>
      )}
      <Tooltip open={expanded ? false : undefined}>
        <TooltipTrigger asChild>
          <button
            aria-label="任务偏好设置"
            className="home-preferences"
            onClick={() => {
              closeDrawer();
              openSettings("memory", { memoryOnly: true });
            }}
            type="button"
          >
            <span aria-hidden="true" className="home-nav-icon-shell">
              <span className="home-preferences-icon" />
            </span>
            {expanded && (
              <>
                <span className="home-preferences-label">任务偏好设置</span>
                <span aria-hidden="true" className="home-preferences-arrow" />
              </>
            )}
          </button>
        </TooltipTrigger>
        {!expanded && (
          <TooltipContent
            className="home-nav-tooltip"
            side="right"
            sideOffset={8}
          >
            任务偏好设置
          </TooltipContent>
        )}
      </Tooltip>
    </nav>
  );
}
