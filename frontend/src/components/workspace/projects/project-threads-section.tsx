"use client";

import { ChevronRight, MessageSquare } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { VirtualThreadList } from "@/components/workspace/thread-list-virtualizer";
import { useI18n } from "@/core/i18n/hooks";
import { type ProjectThreadsQueryResult } from "@/core/projects";
import { pathOfThread } from "@/core/threads/utils";
import { formatTimeAgo } from "@/core/utils/datetime";

export function ProjectThreadsSection({
  query,
}: {
  query: ProjectThreadsQueryResult;
}) {
  const { t } = useI18n();
  const threads = query.data?.pages.flatMap((page) => page) ?? [];
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <h2 className="text-lg font-semibold tracking-tight">
          {t.projects.threads}
        </h2>
        {threads.length > 0 && (
          <span className="text-muted-foreground text-xs tabular-nums">
            {threads.length}
          </span>
        )}
      </div>
      <div>
        {query.isError ? (
          <div className="text-muted-foreground rounded-xl border border-dashed p-5 text-sm">
            {t.projects.threadsLoadFailed}
          </div>
        ) : threads.length === 0 && !query.isLoading ? (
          <div className="text-muted-foreground flex flex-col gap-1 rounded-xl border border-dashed p-5 text-sm">
            <p>{t.projects.empty}</p>
            <p className="text-xs">{t.projects.interimMemoryNotice}</p>
          </div>
        ) : (
          // The page scrolls inside its own ScrollArea; the list windows rows
          // against that viewport so paging through a long-lived project never
          // grows unbounded DOM (same windowing the sidebar and
          // /workspace/chats use).
          <VirtualThreadList
            estimateSize={72}
            items={threads}
            scrollParentSelector='[data-slot="scroll-area-viewport"]'
            renderItem={(thread) => (
              <Link
                key={thread.thread_id}
                href={pathOfThread({
                  thread_id: thread.thread_id,
                  metadata: thread.metadata,
                })}
                data-testid="project-task-row"
                className="group bg-card hover:border-primary/35 focus-visible:ring-ring mb-2 flex min-w-0 items-center gap-3 rounded-xl border px-4 py-3 shadow-sm transition-[border-color,box-shadow,transform] hover:-translate-y-px hover:shadow-md focus-visible:ring-2 focus-visible:outline-none"
              >
                <span className="bg-primary/10 text-primary flex size-9 shrink-0 items-center justify-center rounded-[10px]">
                  <MessageSquare className="size-4" aria-hidden="true" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold">
                    {thread.display_name?.trim()
                      ? thread.display_name
                      : t.projects.untitled}
                  </span>
                  {thread.updated_at && (
                    <span className="text-muted-foreground mt-1 block text-xs">
                      {formatTimeAgo(thread.updated_at)}
                    </span>
                  )}
                </span>
                <ChevronRight
                  className="text-muted-foreground size-4 shrink-0 transition-transform group-hover:translate-x-0.5"
                  aria-hidden="true"
                />
              </Link>
            )}
          />
        )}
      </div>
      {query.hasNextPage && (
        <Button
          variant="ghost"
          size="sm"
          className="justify-center text-xs"
          onClick={() => void query.fetchNextPage()}
          disabled={query.isFetchingNextPage}
          data-testid="project-threads-load-more"
        >
          {query.isFetchingNextPage
            ? t.chats.loadingMore
            : t.chats.loadOlderChats}
        </Button>
      )}
    </section>
  );
}
