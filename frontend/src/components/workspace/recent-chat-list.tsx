"use client";

import {
  Download,
  FileJson,
  FileText,
  ListTodo,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
  Share2,
  Trash2,
} from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
import { ConversationExtensionActions } from "@/components/workspace/conversation-extension-actions";
import { getAPIClient } from "@/core/api";
import { useAuth } from "@/core/auth/AuthProvider";
import { hasPermission, PERMISSIONS } from "@/core/auth/permissions";
import { writeTextToClipboard } from "@/core/clipboard";
import { useI18n } from "@/core/i18n/hooks";
import { isStaticWebsiteOnly } from "@/core/static-mode";
import { exportThread, type ThreadExportFormat } from "@/core/threads/export";
import {
  fetchThreadExportMessages,
  useInfiniteThreads,
  useMoveThreadToProject,
  usePinThread,
  useRenameThread,
} from "@/core/threads/hooks";
import { threadOriginOf } from "@/core/threads/origin";
import {
  flattenThreadBranches,
  type ThreadBranchEntry,
} from "@/core/threads/thread-branch-tree";
import { buildThreadListModel } from "@/core/threads/thread-list-model";
import type { AgentThread, AgentThreadState } from "@/core/threads/types";
import {
  channelSourceOfThread,
  isThreadPinned,
  pathOfThread,
  titleOfThread,
} from "@/core/threads/utils";
import { env } from "@/env";
import { isIMEComposing } from "@/lib/ime";
import { cn } from "@/lib/utils";

import { MoveToProjectMenu, NewProjectDialog } from "./move-to-project-menu";
import {
  ThreadOriginIcon,
  ThreadUnreadDot,
  unreadLabelOfThread,
} from "./thread-channel-source";
import { useThreadDeleteDialog } from "./thread-delete-dialog";
import { VirtualThreadList } from "./thread-list-virtualizer";

/**
 * A single thread row in the sidebar: link + hover action menu (pin, rename,
 * share, export, delete) + rename dialog. Shared by the flat recent-chat list
 * and the grouped-by-project rendering in `ProjectsSection`.
 */
export function ThreadSidebarItem({
  thread,
  isActive,
  branchEntry,
  recentThreadId,
  home = false,
}: {
  home?: boolean;
  thread: AgentThread;
  isActive: boolean;
  branchEntry?: ThreadBranchEntry | undefined;
  recentThreadId?: string | undefined;
}) {
  const { t } = useI18n();
  const { user } = useAuth();
  const canDeleteThreads = hasPermission(user, PERMISSIONS.THREADS_DELETE);
  const requestDelete = useThreadDeleteDialog();
  const { mutate: renameThread } = useRenameThread();
  const { mutate: updatePinnedThread } = usePinThread();
  const { mutate: moveThreadToProject } = useMoveThreadToProject();
  // The move mutation is owned here (not inside `MoveToProjectMenu`) because
  // selecting a project closes the dropdown and unmounts the menu — a
  // per-mutate `onError` registered there would be dropped before a failed
  // request settles, failing silently. This row persists, so a hook-level
  // `onError` always fires. Same ownership-hoisting precedent as the
  // `NewProjectDialog` below.

  const [renameDialogOpen, setRenameDialogOpen] = useState(false);
  const [newTaskGroupDialogOpen, setNewTaskGroupDialogOpen] = useState(false);
  const [renameValue, setRenameValue] = useState("");
  const [exporting, setExporting] = useState(false);

  const handleRenameSubmit = useCallback(() => {
    if (renameValue.trim()) {
      renameThread(
        { threadId: thread.thread_id, title: renameValue.trim() },
        {
          onSuccess: () => {
            setRenameDialogOpen(false);
            setRenameValue("");
          },
          onError: (error) => {
            toast.error(
              error instanceof Error && error.message
                ? error.message
                : t.common.renameFailed,
            );
          },
        },
      );
    }
  }, [renameThread, thread.thread_id, renameValue, t.common.renameFailed]);

  const handleTogglePin = useCallback(() => {
    updatePinnedThread(
      {
        threadId: thread.thread_id,
        pinned: !isThreadPinned(thread),
      },
      {
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : t.chats.pinChatFailed,
          );
        },
      },
    );
  }, [t.chats.pinChatFailed, thread, updatePinnedThread]);

  const handleMoveToTaskGroup = useCallback(
    (projectId: string | null) => {
      moveThreadToProject(
        { threadId: thread.thread_id, projectId },
        {
          onError: (error) => {
            toast.error(
              error instanceof Error && error.message
                ? error.message
                : t.taskGroups.moveFailed,
            );
          },
        },
      );
    },
    [moveThreadToProject, t.taskGroups.moveFailed, thread.thread_id],
  );

  const handleShare = useCallback(async () => {
    // Always use Vercel URL for sharing so others can access
    const VERCEL_URL = "https://deer-flow-v2.vercel.app";
    const isLocalhost =
      window.location.hostname === "localhost" ||
      window.location.hostname === "127.0.0.1";
    // On localhost: use Vercel URL; On production: use current origin
    const baseUrl = isLocalhost ? VERCEL_URL : window.location.origin;
    const shareUrl = `${baseUrl}${pathOfThread(thread)}`;
    try {
      const didCopy = await writeTextToClipboard(shareUrl);
      if (!didCopy) {
        toast.error(t.clipboard.failedToCopyToClipboard);
        return;
      }

      toast.success(t.clipboard.linkCopied);
    } catch {
      toast.error(t.clipboard.failedToCopyToClipboard);
    }
  }, [t, thread]);

  const handleExport = useCallback(
    async (format: ThreadExportFormat) => {
      setExporting(true);
      try {
        const messages = isStaticWebsiteOnly()
          ? ((
              await getAPIClient().threads.getState<AgentThreadState>(
                thread.thread_id,
              )
            ).values?.messages ?? [])
          : await fetchThreadExportMessages(thread.thread_id);
        if (messages.length === 0) {
          toast.error(t.conversation.noMessages);
          return;
        }
        exportThread(thread, messages, format);
        toast.success(t.common.exportSuccess);
      } catch (error) {
        console.error(error);
        toast.error(t.common.exportFailed);
      } finally {
        setExporting(false);
      }
    },
    [t, thread],
  );

  const channelSource = channelSourceOfThread(thread, t);
  const origin = threadOriginOf(thread);
  const pinned = isThreadPinned(thread);
  const parentTitle = branchEntry?.parentThread
    ? titleOfThread(branchEntry.parentThread, t.pages.untitled)
    : null;
  const title = titleOfThread(thread, t.pages.untitled);
  const branchLabel = parentTitle
    ? t.chats.branchLabel(title, parentTitle)
    : undefined;
  // The open thread is being read, so it never shows the dot (the chat page
  // clears its server-side unread state).
  const unread = thread.unread === true && !isActive;
  const statusIcon = home ? homeTaskStatus(thread.status, unread) : null;
  const rowLabel = unread
    ? unreadLabelOfThread(branchLabel ?? title, t, origin)
    : branchLabel;

  return (
    <SidebarMenuItem className="group/side-menu-item">
      <SidebarMenuButton isActive={isActive} asChild>
        <Link
          aria-label={rowLabel}
          className="text-muted-foreground min-w-0 whitespace-nowrap group-hover/side-menu-item:overflow-hidden"
          data-unread={unread ? "true" : undefined}
          data-branch-depth={
            branchEntry && branchEntry.depth > 0 ? branchEntry.depth : undefined
          }
          data-branch-parent-id={branchEntry?.parentThread?.thread_id}
          aria-current={isActive ? "page" : undefined}
          href={pathOfThread(thread)}
          title={branchLabel}
        >
          {branchEntry && branchEntry.depth > 0 && (
            <span
              aria-hidden="true"
              className="text-muted-foreground/70 shrink-0 font-mono text-[10px] leading-none"
              data-testid="thread-branch-stem"
              style={{
                marginLeft: `${Math.min(branchEntry.depth - 1, 1) * 8}px`,
              }}
            >
              {branchEntry.isLastSibling ? "└─" : "├─"}
            </span>
          )}
          <ThreadOriginIcon origin={origin} />
          {pinned && !home && (
            <Pin
              aria-hidden="true"
              className="text-muted-foreground size-3.5 shrink-0"
            />
          )}
          <span
            className={cn(
              "min-w-0 truncate",
              home && isActive && "home-task-active-label",
            )}
          >
            {title}
          </span>
          {(channelSource !== null || (unread && !home)) && (
            <span className="ml-auto inline-flex shrink-0 items-center gap-1.5">
              {channelSource && (
                <span
                  className="bg-muted text-muted-foreground inline-flex h-5 max-w-14 shrink-0 items-center rounded-md px-1.5 text-[10px] font-medium"
                  title={t.threads.origin.fromProvider(channelSource.label)}
                >
                  <span className="truncate">{channelSource.label}</span>
                </span>
              )}
              {unread && !home && <ThreadUnreadDot />}
            </span>
          )}
          {statusIcon && (
            <Image
              alt={statusIcon.label}
              className="home-task-status"
              height={12}
              src={`/images/cecemate-home/task-${statusIcon.icon}.svg`}
              title={statusIcon.label}
              width={12}
            />
          )}
        </Link>
      </SidebarMenuButton>
      {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuAction
              showOnHover
              className={cn(
                "bg-background/50 hover:bg-background after:left-0!",
                home && "home-task-more-action",
              )}
            >
              {home ? (
                <span aria-hidden="true" className="home-task-more-icon" />
              ) : (
                <MoreHorizontal />
              )}
              <span className="sr-only">{t.common.more}</span>
            </SidebarMenuAction>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className={
              home
                ? "home-task-menu"
                : "w-48 rounded-lg border-[#dfe6f3] bg-white text-[#26324a] shadow-[0_8px_24px_rgb(20_32_64_/_0.12)] [&_[data-slot=dropdown-menu-item]:focus]:bg-[#eef3ff] [&_[data-slot=dropdown-menu-item]:focus]:text-[#2563eb] [&_[data-slot=dropdown-menu-sub-content]]:border-[#dfe6f3] [&_[data-slot=dropdown-menu-sub-content]]:bg-white [&_[data-slot=dropdown-menu-sub-content]]:text-[#26324a] [&_[data-slot=dropdown-menu-sub-trigger]:focus]:bg-[#eef3ff] [&_[data-slot=dropdown-menu-sub-trigger]:focus]:text-[#2563eb]"
            }
            side={"right"}
            align={"start"}
            sideOffset={home ? 8 : undefined}
          >
            {home ? (
              <>
                <DropdownMenuItem
                  className="home-task-menu-item"
                  onSelect={handleTogglePin}
                >
                  <span
                    aria-hidden="true"
                    className="home-task-menu-icon"
                    data-icon={pinned ? "unpin" : "pin"}
                  />
                  <span>{pinned ? "取消置顶" : "置顶对话"}</span>
                </DropdownMenuItem>
                <DropdownMenuItem
                  className="home-task-menu-item"
                  onSelect={() => {
                    setRenameValue(titleOfThread(thread, t.pages.untitled));
                    setRenameDialogOpen(true);
                  }}
                >
                  <span
                    aria-hidden="true"
                    className="home-task-menu-icon"
                    data-icon="rename"
                  />
                  <span>重命名</span>
                </DropdownMenuItem>
                {canDeleteThreads && (
                  <DropdownMenuItem
                    className="home-task-menu-item"
                    onSelect={() => requestDelete({ thread, recentThreadId })}
                  >
                    <span
                      aria-hidden="true"
                      className="home-task-menu-icon"
                      data-icon="delete"
                    />
                    <span>删除</span>
                  </DropdownMenuItem>
                )}
              </>
            ) : (
              <>
                <ConversationExtensionActions
                  context={{ thread }}
                  placement="menu"
                />
                <DropdownMenuItem onSelect={handleTogglePin}>
                  {pinned ? (
                    <PinOff className="text-muted-foreground" />
                  ) : (
                    <Pin className="text-muted-foreground" />
                  )}
                  <span>{pinned ? t.chats.unpinChat : t.chats.pinChat}</span>
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={() => {
                    setRenameValue(titleOfThread(thread, t.pages.untitled));
                    setRenameDialogOpen(true);
                  }}
                >
                  <Pencil className="text-muted-foreground" />
                  <span>{t.common.rename}</span>
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => void handleShare()}>
                  <Share2 className="text-muted-foreground" />
                  <span>{t.common.share}</span>
                </DropdownMenuItem>
                <DropdownMenuSub>
                  <DropdownMenuSubTrigger disabled={exporting}>
                    <Download className="text-muted-foreground" />
                    <span>{t.common.export}</span>
                  </DropdownMenuSubTrigger>
                  <DropdownMenuSubContent>
                    <DropdownMenuItem
                      onSelect={() => void handleExport("markdown")}
                    >
                      <FileText className="text-muted-foreground" />
                      <span>{t.common.exportAsMarkdown}</span>
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onSelect={() => void handleExport("json")}
                    >
                      <FileJson className="text-muted-foreground" />
                      <span>{t.common.exportAsJSON}</span>
                    </DropdownMenuItem>
                  </DropdownMenuSubContent>
                </DropdownMenuSub>
                <DropdownMenuSeparator />
                <MoveToProjectMenu
                  thread={thread}
                  onNewProject={() => setNewTaskGroupDialogOpen(true)}
                  onMoveProject={handleMoveToTaskGroup}
                />
                {canDeleteThreads && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      onSelect={() => requestDelete({ thread, recentThreadId })}
                    >
                      <Trash2 className="text-muted-foreground" />
                      <span>{t.common.delete}</span>
                    </DropdownMenuItem>
                  </>
                )}
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      )}

      {/* Rename Dialog */}
      <Dialog open={renameDialogOpen} onOpenChange={setRenameDialogOpen}>
        <DialogContent className="ce-task-dialog sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{t.common.rename}</DialogTitle>
          </DialogHeader>
          <div className="py-4">
            <Input
              className="ce-task-dialog-input"
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              placeholder={t.common.rename}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !isIMEComposing(e)) {
                  e.preventDefault();
                  handleRenameSubmit();
                }
              }}
            />
          </div>
          <DialogFooter>
            <Button
              className="ce-task-dialog-button ce-task-dialog-button-neutral"
              variant="outline"
              onClick={() => setRenameDialogOpen(false)}
            >
              {t.common.cancel}
            </Button>
            <Button
              className="ce-task-dialog-button ce-task-dialog-button-primary"
              onClick={handleRenameSubmit}
            >
              {t.common.save}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <NewProjectDialog
        thread={thread}
        open={newTaskGroupDialogOpen}
        onOpenChange={setNewTaskGroupDialogOpen}
      />
    </SidebarMenuItem>
  );
}

function homeTaskStatus(status: AgentThread["status"], unread: boolean) {
  switch (status) {
    case "busy":
      return { icon: "busy", label: "运行中" };
    case "interrupted":
      return { icon: "interrupted", label: "已中断" };
    case "error":
      return { icon: "error", label: "出错" };
    default:
      return unread ? { icon: "unread", label: "未读" } : null;
  }
}

export function RecentChatList({ home = false }: { home?: boolean } = {}) {
  const [searching, setSearching] = useState(false);
  const [query, setQuery] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setSearchTerm(query.trim()), 180);
    return () => clearTimeout(timer);
  }, [query]);
  const [expanded, setExpanded] = useState(true);
  const searchButton = useRef<HTMLButtonElement>(null);
  const listVisible = !home || searching || expanded;
  const { t } = useI18n();
  const { thread_id: threadIdFromPath } = useParams<{
    thread_id: string;
    agent_name?: string;
  }>();
  const {
    data: infiniteThreads,
    isFetching,
    isError,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteThreads({
    ...(home && searchTerm && query.trim() && !isStaticWebsiteOnly()
      ? { query: searchTerm }
      : {}),
    archived:
      env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ? undefined : false,
  });
  const threadListModel = useMemo(
    () => buildThreadListModel(infiniteThreads?.pages ?? []),
    [infiniteThreads?.pages],
  );
  const { threads } = threadListModel;
  const displayedThreads = useMemo(() => {
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
  const visibleThreads = useMemo(() => {
    const keyword = query.trim().toLocaleLowerCase();
    return home && keyword
      ? threads.filter((thread) =>
          titleOfThread(thread, t.pages.untitled)
            .toLocaleLowerCase()
            .includes(keyword),
        )
      : displayedThreads;
  }, [home, query, threads, displayedThreads, t.pages.untitled]);
  const pinnedThreads = useMemo(
    () => (home ? visibleThreads.filter(isThreadPinned) : []),
    [home, visibleThreads],
  );
  const recentThreads = useMemo(
    () =>
      home
        ? visibleThreads.filter((thread) => !isThreadPinned(thread))
        : visibleThreads,
    [home, visibleThreads],
  );
  const branchList = useMemo(() => {
    const entries = flattenThreadBranches(recentThreads);
    return {
      entriesById: new Map(
        entries.map((entry) => [entry.thread.thread_id, entry]),
      ),
      threads: entries.map((entry) => entry.thread),
    };
  }, [recentThreads]);
  const pinnedBranchList = useMemo(() => {
    const entries = flattenThreadBranches(pinnedThreads);
    return {
      entriesById: new Map(
        entries.map((entry) => [entry.thread.thread_id, entry]),
      ),
      threads: entries.map((entry) => entry.thread),
    };
  }, [pinnedThreads]);

  const sentinelRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const element = sentinelRef.current;
    if (!element || !hasNextPage || !threadListModel.canLoadMore) {
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting && hasNextPage && !isFetchingNextPage) {
          void fetchNextPage();
        }
      },
      { rootMargin: "120px 0px 120px 0px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    listVisible,
    threadListModel.canLoadMore,
  ]);

  // Grouped mode moves project threads under `ProjectsSection`, so this list
  // can be empty while older pages (possibly holding unassigned threads) still
  // exist on the server. Keep the pagination controls mounted then; flat mode
  // keeps the original "empty list renders nothing" behavior.
  return (
    <SidebarGroup className="px-0 pt-0">
      {home && pinnedBranchList.threads.length > 0 && (
        <div className="home-pinned-tasks">
          <p>置顶任务</p>
          <SidebarMenu>
            {pinnedBranchList.threads.map((thread) => (
              <ThreadSidebarItem
                key={thread.thread_id}
                thread={thread}
                home
                isActive={thread.thread_id === threadIdFromPath}
                branchEntry={pinnedBranchList.entriesById.get(thread.thread_id)}
                recentThreadId={threads[0]?.thread_id}
              />
            ))}
          </SidebarMenu>
        </div>
      )}
      {home ? (
        <div className="home-history-header">
          {searching ? (
            <label className="home-history-search">
              <Image
                alt=""
                aria-hidden="true"
                height={14}
                src="/images/cecemate-home/search.svg"
                width={14}
              />
              <input
                autoFocus
                type="search"
                placeholder="搜索任务"
                aria-label="搜索任务"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onBlur={() => {
                  if (!query.trim()) setSearching(false);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Escape" && !isIMEComposing(event)) {
                    setQuery("");
                    setSearching(false);
                    requestAnimationFrame(() => searchButton.current?.focus());
                  }
                }}
              />
            </label>
          ) : (
            <>
              <button
                type="button"
                aria-expanded={expanded}
                onClick={() => setExpanded(!expanded)}
              >
                最近任务 ({recentThreads.length}
                {hasNextPage ? "+" : ""}){" "}
                <Image
                  alt=""
                  aria-hidden="true"
                  height={14}
                  src="/images/cecemate-home/chevron-down.svg"
                  width={14}
                  className={expanded ? "" : "-rotate-90"}
                />
              </button>
              <button
                ref={searchButton}
                type="button"
                aria-label="搜索任务"
                onClick={() => setSearching(true)}
              >
                <Image
                  alt=""
                  aria-hidden="true"
                  height={15}
                  src="/images/cecemate-home/search.svg"
                  width={15}
                />
              </button>
            </>
          )}
        </div>
      ) : (
        <SidebarGroupLabel className="h-[30px] gap-2 px-2.5 text-[13px] font-medium text-[#5a6478]">
          <ListTodo className="size-4" />
          全部任务
        </SidebarGroupLabel>
      )}
      {listVisible && (
        <SidebarGroupContent className="group-data-[collapsible=icon]:pointer-events-none group-data-[collapsible=icon]:-mt-8 group-data-[collapsible=icon]:opacity-0">
          <SidebarMenu className="pl-3">
            {/* Keep pagination at the old list boundary when this switches to virtual rows. */}
            <div
              className="flex w-full flex-col gap-1"
              style={{ overflowAnchor: "none" }}
            >
              <VirtualThreadList
                estimateSize={36}
                gap={4}
                items={branchList.threads}
                scrollParentSelector='[data-sidebar="content"]'
                renderItem={(thread) => (
                  <ThreadSidebarItem
                    key={thread.thread_id}
                    thread={thread}
                    home={home}
                    isActive={thread.thread_id === threadIdFromPath}
                    branchEntry={branchList.entriesById.get(thread.thread_id)}
                    recentThreadId={threads[0]?.thread_id}
                  />
                )}
              />
              {home &&
                query.trim() &&
                !branchList.threads.length &&
                !pinnedBranchList.threads.length && (
                  <p className="py-2 text-xs text-[#8994a1]" role="status">
                    {isError
                      ? "任务搜索失败"
                      : isFetching ||
                          (!isStaticWebsiteOnly() &&
                            query.trim() !== searchTerm)
                        ? "正在搜索…"
                        : "未找到匹配任务"}
                  </p>
                )}
              {hasNextPage && threadListModel.canLoadMore && (
                <>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="mx-2 my-1 w-[calc(100%-1rem)] justify-center text-xs"
                    onClick={() => void fetchNextPage()}
                    disabled={isFetchingNextPage}
                    data-testid="recent-chat-list-load-more"
                  >
                    {isFetchingNextPage
                      ? t.chats.loadingMore
                      : t.chats.loadOlderChats}
                  </Button>
                  <div
                    ref={sentinelRef}
                    aria-hidden="true"
                    className="h-px w-full"
                    data-testid="recent-chat-list-sentinel"
                  />
                </>
              )}
            </div>
          </SidebarMenu>
        </SidebarGroupContent>
      )}
    </SidebarGroup>
  );
}
