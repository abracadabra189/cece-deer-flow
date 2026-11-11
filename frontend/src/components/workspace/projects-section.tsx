"use client";

import { Archive, ChevronRight, Folder, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";
import { useCreateProject, useProjects, type Project } from "@/core/projects";
import { isStaticWebsiteOnly } from "@/core/static-mode";
import { useInfiniteThreads } from "@/core/threads/hooks";
import { flattenThreadBranches } from "@/core/threads/thread-branch-tree";
import { buildThreadListModel } from "@/core/threads/thread-list-model";
import type { AgentThread } from "@/core/threads/types";
import { pathOfThread, projectIdOfThread } from "@/core/threads/utils";
import { env } from "@/env";
import { isIMEComposing } from "@/lib/ime";

import { ThreadSidebarItem } from "./recent-chat-list";

function projectPath(projectId: string): string {
  return `/workspace/projects/${projectId}`;
}

function ProjectThreadGroup({
  project,
  threads,
  recentThreadId,
}: {
  project: Project;
  threads: readonly AgentThread[];
  /** Global most-recent thread id — mirrors flat mode's `threads[0]?.thread_id`. */
  recentThreadId: string | undefined;
}) {
  const pathname = usePathname();
  const [open, setOpen] = useState(true);
  const href = projectPath(project.id);
  const branchEntries = useMemo(
    () => flattenThreadBranches([...threads]),
    [threads],
  );
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <SidebarMenuItem>
        <SidebarMenuButton asChild isActive={pathname === href}>
          <Link href={href} title={project.name}>
            <Folder />
            <span className="min-w-0 truncate">{project.name}</span>
          </Link>
        </SidebarMenuButton>
        <CollapsibleTrigger asChild>
          <SidebarMenuAction
            aria-label={project.name}
            className="[&>svg]:transition-transform [&[data-state=open]>svg]:rotate-90"
          >
            <ChevronRight />
          </SidebarMenuAction>
        </CollapsibleTrigger>
      </SidebarMenuItem>
      <CollapsibleContent>
        <SidebarMenu className="border-sidebar-border ml-4 w-auto border-l pl-2">
          {branchEntries.map((entry) => (
            <ThreadSidebarItem
              key={entry.thread.thread_id}
              thread={entry.thread}
              isActive={pathOfThread(entry.thread) === pathname}
              branchEntry={entry}
              recentThreadId={recentThreadId}
            />
          ))}
        </SidebarMenu>
      </CollapsibleContent>
    </Collapsible>
  );
}

function ArchivedProjectsGroup({
  projects,
  threadsByProject,
  recentThreadId,
}: {
  projects: readonly Project[];
  threadsByProject: ReadonlyMap<string, readonly AgentThread[]>;
  recentThreadId: string | undefined;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <SidebarMenuItem>
        <CollapsibleTrigger asChild>
          <SidebarMenuButton>
            <Archive />
            <span className="min-w-0 truncate">{t.projects.archived}</span>
            <ChevronRight className="ml-auto transition-transform [[data-state=open]>&]:rotate-90" />
          </SidebarMenuButton>
        </CollapsibleTrigger>
      </SidebarMenuItem>
      <CollapsibleContent>
        <SidebarMenu className="border-sidebar-border ml-4 w-auto border-l pl-2">
          {projects.map((project) => (
            <ProjectThreadGroup
              key={project.id}
              project={project}
              threads={threadsByProject.get(project.id) ?? []}
              recentThreadId={recentThreadId}
            />
          ))}
        </SidebarMenu>
      </CollapsibleContent>
    </Collapsible>
  );
}

/**
 * Grouped mode: active projects as collapsible headers with their recent
 * threads (grouped client-side from the already-fetched infinite thread
 * pages), plus a collapsed "Archived" section at the bottom.
 */
function GroupedProjectList() {
  const { data: activeProjects } = useProjects("active");
  const { data: archivedProjects } = useProjects("archived");
  const { data: infiniteThreads } = useInfiniteThreads({
    archived:
      env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ? undefined : false,
  });
  const { thread_id: threadIdFromPath } = useParams<{
    thread_id: string;
    agent_name?: string;
  }>();
  const threadListModel = useMemo(
    () => buildThreadListModel(infiniteThreads?.pages ?? []),
    [infiniteThreads?.pages],
  );
  // Same value flat mode passes to `ThreadSidebarItem` — the global most-recent
  // thread, NOT the capped displayedThreads or any group-local first entry.
  const globalRecentThreadId = threadListModel.threads[0]?.thread_id;
  // Mirror `RecentChatList`'s active-thread exception: the path-active thread
  // is appended even when it falls beyond the unpinned display cap, so it
  // must join the partition input too — otherwise an active assigned chat
  // renders in neither the flat list nor its project group.
  const partitionableThreads = useMemo(() => {
    if (
      !threadIdFromPath ||
      threadListModel.displayedThreads.some(
        (thread) => thread.thread_id === threadIdFromPath,
      )
    ) {
      return threadListModel.displayedThreads;
    }
    const activeThread = threadListModel.byId.get(threadIdFromPath);
    return activeThread
      ? [...threadListModel.displayedThreads, activeThread]
      : threadListModel.displayedThreads;
  }, [threadIdFromPath, threadListModel]);
  const threadsByProject = useMemo(() => {
    const grouped = new Map<string, AgentThread[]>();
    for (const thread of partitionableThreads) {
      const projectId = projectIdOfThread(thread);
      if (projectId === null) {
        continue;
      }
      const projectThreads = grouped.get(projectId);
      if (projectThreads) {
        projectThreads.push(thread);
      } else {
        grouped.set(projectId, [thread]);
      }
    }
    return grouped;
  }, [partitionableThreads]);

  if (
    (!activeProjects || activeProjects.length === 0) &&
    (!archivedProjects || archivedProjects.length === 0)
  ) {
    return null;
  }
  return (
    <SidebarMenu>
      {activeProjects?.map((project) => (
        <ProjectThreadGroup
          key={project.id}
          project={project}
          threads={threadsByProject.get(project.id) ?? []}
          recentThreadId={globalRecentThreadId}
        />
      ))}
      {archivedProjects && archivedProjects.length > 0 && (
        <ArchivedProjectsGroup
          projects={archivedProjects}
          threadsByProject={threadsByProject}
          recentThreadId={globalRecentThreadId}
        />
      )}
    </SidebarMenu>
  );
}

export function ProjectsSection() {
  const { t } = useI18n();
  const { mutate: createProject, isPending: isCreating } = useCreateProject();

  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [createName, setCreateName] = useState("");

  const handleCreateSubmit = useCallback(() => {
    const name = createName.trim();
    if (!name || isCreating) {
      return;
    }
    createProject(
      { name },
      {
        onSuccess: () => {
          setCreateDialogOpen(false);
          setCreateName("");
        },
        onError: (error) => {
          toast.error(
            error instanceof Error && error.message
              ? error.message
              : t.taskGroups.createFailed,
          );
        },
      },
    );
  }, [createProject, createName, isCreating, t.taskGroups.createFailed]);

  // Static-demo mode has no Gateway and no projects: hide the whole section
  // (New task group button and groups are all dead actions).
  if (isStaticWebsiteOnly()) {
    return null;
  }

  return (
    <SidebarGroup className="mt-1 border-t border-[#e7ebf3] px-0 pt-1">
      <SidebarGroupLabel className="h-[30px] justify-between px-2.5 text-[13px] font-medium text-[#5a6478]">
        <span>{t.taskGroups.title}</span>
        <span className="flex items-center gap-0.5">
          <Button
            variant="ghost"
            size="icon"
            className="size-5 [&>svg]:size-3.5"
            title={t.taskGroups.newTaskGroup}
            aria-label={t.taskGroups.newTaskGroup}
            onClick={() => setCreateDialogOpen(true)}
            data-testid="projects-new-project-button"
          >
            <Plus />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="size-5 [&>svg]:size-3.5"
            title={t.trash.title}
            aria-label={t.trash.title}
            asChild
            data-testid="projects-trash-link"
          >
            <Link href="/workspace/trash">
              <Trash2 />
            </Link>
          </Button>
        </span>
      </SidebarGroupLabel>
      <SidebarGroupContent className="group-data-[collapsible=icon]:pointer-events-none group-data-[collapsible=icon]:-mt-8 group-data-[collapsible=icon]:opacity-0">
        <GroupedProjectList />
      </SidebarGroupContent>

      {/* New project dialog */}
      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{t.taskGroups.newTaskGroup}</DialogTitle>
          </DialogHeader>
          <div className="py-4">
            <Input
              value={createName}
              onChange={(e) => setCreateName(e.target.value)}
              placeholder={t.taskGroups.namePlaceholder}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !isIMEComposing(e)) {
                  e.preventDefault();
                  handleCreateSubmit();
                }
              }}
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setCreateDialogOpen(false)}
            >
              {t.common.cancel}
            </Button>
            <Button
              onClick={handleCreateSubmit}
              disabled={!createName.trim() || isCreating}
            >
              {t.projects.create}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </SidebarGroup>
  );
}
