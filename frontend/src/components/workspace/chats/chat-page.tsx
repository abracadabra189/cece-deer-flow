"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { type PromptInputMessage } from "@/components/ai-elements/prompt-input";
import { ArtifactTrigger } from "@/components/workspace/artifacts";
import { BrowserTrigger } from "@/components/workspace/browser-view";
import { GoalStatus } from "@/components/workspace/goal-status";
import {
  InputBox,
  type InputBoxSubmitOptions,
} from "@/components/workspace/input-box";
import { KnowledgeScopeSelector } from "@/components/workspace/knowledge-scope-selector";
import {
  MessageList,
  MESSAGE_LIST_DEFAULT_PADDING_BOTTOM,
} from "@/components/workspace/messages";
import { ThreadContext } from "@/components/workspace/messages/context";
import { HumanInputCard } from "@/components/workspace/messages/human-input-card";
import {
  SidecarProvider,
  SidecarTrigger,
} from "@/components/workspace/sidecar";
import { ThreadRunInputs } from "@/components/workspace/thread-run-inputs";
import { ThreadTitle } from "@/components/workspace/thread-title";
import { TodoList } from "@/components/workspace/todo-list";
import { useActiveGoal } from "@/components/workspace/use-active-goal";
import { Welcome } from "@/components/workspace/welcome";
import { WorkspaceSidebarTrigger } from "@/components/workspace/workspace-sidebar-trigger";
import { useAuth } from "@/core/auth/AuthProvider";
import { hasPermission, PERMISSIONS } from "@/core/auth/permissions";
import {
  useBrowserControlEnabled,
  useKnowledgeBaseEnabled,
} from "@/core/features";
import { useI18n } from "@/core/i18n/hooks";
import {
  ALL_KNOWLEDGE_SCOPE,
  buildKnowledgeScopeSnapshot,
  KNOWLEDGE_SCOPE_KEY,
  type KnowledgeScopeSelection,
} from "@/core/knowledge";
import {
  buildHumanInputResponseText,
  hasOpenHumanInputRequest,
  type HumanInputRequest,
  type HumanInputResponse,
} from "@/core/messages/human-input";
import { isHiddenFromUIMessage } from "@/core/messages/utils";
import { modelTaskInput } from "@/core/models/control";
import { useModelControl } from "@/core/models/use-model-control";
import { notificationBody } from "@/core/notification/body";
import { useNotification } from "@/core/notification/hooks";
import { useThreadScheduledTaskEvents } from "@/core/scheduled-tasks/events";
import { useScheduleToolResultRefresh } from "@/core/scheduled-tasks/hooks";
import { useThreadSettings } from "@/core/settings";
import { resolveThreadContext, selectThreadModel } from "@/core/settings/store";
import { createThread } from "@/core/threads/api";
import {
  useBranchThread,
  INFINITE_THREADS_QUERY_KEY_PREFIX,
  useThreadMetadata,
  useThreadStream,
} from "@/core/threads/hooks";
import { projectIdOfThread, textOfMessage } from "@/core/threads/utils";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import { ChatBox } from "./chat-box";
import { useSpecificChatMode } from "./use-chat-mode";
import { useMarkOpenThreadRead } from "./use-mark-open-thread-read";
import { useThreadChat } from "./use-thread-chat";

export default function ChatPage() {
  const { t, locale } = useI18n();
  const { user } = useAuth();
  const canStopStreaming = hasPermission(user, PERMISSIONS.RUNS_CANCEL);
  const canCreateRuns = hasPermission(user, PERMISSIONS.RUNS_CREATE);
  const router = useRouter();
  const searchParams = useSearchParams();
  const { threadId, setThreadId, isNewThread, setIsNewThread, isMock } =
    useThreadChat();
  const projectParam = isNewThread ? searchParams.get("project") : null;
  // `isNewThread` tracks whether the backend has the thread yet — gates the
  // SDK's history fetch (see issue #2746).  `isWelcomeMode` is the visual
  // welcome layout (centered input, hero, quick actions); we flip it to false
  // the moment the user submits so the UI animates immediately, even though
  // `isNewThread` stays true until the backend actually creates the thread.
  const [isWelcomeMode, setIsWelcomeMode] = useState(isNewThread);
  const queryClient = useQueryClient();
  const [settings, setSettings] = useThreadSettings(threadId);
  const modelControl = useModelControl(
    `${user?.id ?? "anonymous"}:${threadId}`,
    locale,
  );
  const prepareModelControl = modelControl.prepare;
  const [modelChoiceSummary, setModelChoiceSummary] = useState("");
  useEffect(() => setModelChoiceSummary(""), [threadId, user?.id]);
  const { enabled: browserControlEnabled } = useBrowserControlEnabled();
  const threadMetadata = useThreadMetadata(threadId, {
    enabled: !isNewThread && !isMock,
    isMock,
  });
  // A saved thread that exists on the server is being read while open:
  // clears its unread dot (sidebar and chats list) on every device.
  const markThreadRead = useMarkOpenThreadRead(threadId, {
    enabled: !isNewThread && !isMock && threadMetadata.data != null,
  });
  // Lifecycle lines of schedules created in this chat ("Paused by agent",
  // "Finished"); they stay after the task is deleted.
  const scheduledTaskEvents = useThreadScheduledTaskEvents(threadId, {
    isNewThread,
    enabled: !isMock,
  });
  const branchThread = useBranchThread();
  const mountedRef = useRef(false);
  useSpecificChatMode();

  useEffect(() => {
    mountedRef.current = true;
  }, []);

  // Keep welcome layout in sync when navigating between threads (sidebar
  // clicks, "new chat" button).  Submitting in /chats/new flips the layout
  // via onSend below — `isNewThread` stays true until onStart, so this effect
  // is harmless during the submit transition.
  useEffect(() => {
    setIsWelcomeMode(isNewThread);
  }, [isNewThread]);

  const { showNotification } = useNotification();
  const { scopeSelectionEnabled } = useKnowledgeBaseEnabled();
  const selectorVisible =
    scopeSelectionEnabled && env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true";
  const [knowledgeScope, setKnowledgeScope] =
    useState<KnowledgeScopeSelection | null>(null);
  const previousConversationRef = useRef({ threadId, isNewThread });

  useEffect(() => {
    setKnowledgeScope((current) => {
      if (!selectorVisible) return null;
      return current ?? ALL_KNOWLEDGE_SCOPE;
    });
  }, [selectorVisible]);

  useEffect(() => {
    const previous = previousConversationRef.current;
    if (
      previous.threadId !== threadId ||
      previous.isNewThread !== isNewThread
    ) {
      const isNewThreadRouteReplacement = previous.isNewThread && !isNewThread;
      if (!isNewThreadRouteReplacement) {
        setKnowledgeScope(selectorVisible ? ALL_KNOWLEDGE_SCOPE : null);
      }
    }
    previousConversationRef.current = { threadId, isNewThread };
  }, [isNewThread, selectorVisible, threadId]);

  const currentKnowledgeScopeSnapshot = useMemo(
    () =>
      selectorVisible && knowledgeScope
        ? buildKnowledgeScopeSnapshot(knowledgeScope)
        : null,
    [knowledgeScope, selectorVisible],
  );

  const {
    thread,
    sendMessage,
    sendInput,
    runInputs,
    canSendInput,
    activeRunId,
    activeRunStartedAt,
    regenerateMessage,
    editAndRegenerateMessage,
    isUploading,
    isHistoryLoading,
    hasMoreHistory,
    loadMoreHistory,
    approvalRequests,
    hasPendingApproval,
    submitHitlApproval,
    waitingForInputRunIds,
  } = useThreadStream({
    threadId: isNewThread ? undefined : threadId,
    displayThreadId: threadId,
    context: settings.context,
    isMock,
    // onSend only animates the UI; do NOT flip `isNewThread` here — the
    // LangGraph SDK eagerly fetches /history the moment it receives a
    // thread id and assumes the thread exists on the backend (issue #2746).
    onSend: () => {
      setIsWelcomeMode(false);
    },
    onStart: (createdThreadId) => {
      // ! Important: Never use next.js router for navigation in this case, otherwise it will cause the thread to re-mount and lose all states. Use native history API instead.
      history.replaceState(null, "", `/workspace/chats/${createdThreadId}`);
      setThreadId(createdThreadId);
      setIsNewThread(false);
    },
    onFinish: (state) => {
      // A run in this thread ended (a send, or a joined scheduled run) while
      // it is open: it has been read.
      markThreadRead();
      if (document.hidden || !document.hasFocus()) {
        const lastMessage = state.messages.at(-1);
        showNotification(state.title, {
          body: notificationBody(
            lastMessage ? textOfMessage(lastMessage) : null,
          ),
        });
      }
    },
    restInterrupts: threadMetadata.data?.interrupts,
    restInterruptsLoading: threadMetadata.isLoading,
    restInterruptsError: threadMetadata.isError,
  });

  const hasThreadMessages = thread.messages.length > 0;
  // A schedule_task result refreshes the header button and cards at once.
  useScheduleToolResultRefresh(isMock ? null : threadId, thread.messages);

  useEffect(() => {
    if (
      !isNewThread &&
      !isMock &&
      threadMetadata.data === null &&
      !threadMetadata.isLoading &&
      !threadMetadata.isFetching &&
      !isHistoryLoading &&
      !hasMoreHistory &&
      !hasThreadMessages
    ) {
      router.replace("/workspace/chats/new");
    }
  }, [
    hasMoreHistory,
    hasThreadMessages,
    isHistoryLoading,
    isMock,
    isNewThread,
    router,
    threadMetadata.data,
    threadMetadata.isFetching,
    threadMetadata.isLoading,
  ]);

  // A project-scoped new chat must create its thread with the project before
  // the first run; otherwise the backend creates an unassigned thread first.
  const ensureProjectThread = useCallback(async () => {
    if (!projectParam) return;
    try {
      const created = await createThread(threadId, projectParam);
      queryClient.setQueryData(
        ["thread", "metadata", threadId, false],
        created,
      );
      void queryClient.invalidateQueries({
        queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
      });
    } catch (error) {
      toast.error(t.projects.projectUnavailable);
      throw error;
    }
  }, [projectParam, queryClient, t, threadId]);

  // Submission fence: if a user navigates while model selection or project
  // creation is open, a stale continuation must not start a run elsewhere.
  const submissionEpochRef = useRef(0);
  useEffect(() => {
    return () => {
      submissionEpochRef.current += 1;
    };
  }, [projectParam, threadId]);

  const handleSubmit = useCallback(
    async (message: PromptInputMessage, options?: InputBoxSubmitOptions) => {
      const submissionEpoch = submissionEpochRef.current;
      setModelChoiceSummary("");
      const choice = await prepareModelControl(message.text);
      const modelInput = modelTaskInput(message.text, choice);
      if (submissionEpochRef.current !== submissionEpoch)
        throw new Error("thread-submission-stale");
      const runModelContext: Record<string, unknown> = {};
      if (choice?.model_name) {
        if (choice.scope === "task") {
          if (settings.context.mode !== "ultra") {
            toast.error(
              locale.startsWith("zh")
                ? "当前未启用子任务，请先启用 Ultra 模式。"
                : "Subtasks are disabled. Enable Ultra mode first.",
            );
            throw new Error("subtasks-disabled");
          }
          runModelContext.subagent_model_name = choice.model_name;
        } else {
          runModelContext.model_name = choice.model_name;
          runModelContext.model_selection_requested = choice.model_name;
        }
      }
      await ensureProjectThread();
      if (submissionEpochRef.current !== submissionEpoch) {
        throw new Error("thread-submission-stale");
      }
      if (
        choice?.scope === "conversation" &&
        !modelInput.text &&
        message.files.length === 0 &&
        isNewThread &&
        !projectParam
      ) {
        await createThread(threadId);
        if (submissionEpochRef.current !== submissionEpoch)
          throw new Error("thread-submission-stale");
      }
      if (choice?.model_name) {
        if (choice.scope === "conversation")
          try {
            selectThreadModel(threadId, choice.model_name);
          } catch (error) {
            toast.error(
              locale.startsWith("zh")
                ? "无法在浏览器保存本对话的默认模型，请检查存储权限。"
                : "Unable to save this conversation's default model. Check browser storage permissions.",
            );
            throw error;
          }
        const label =
          choice.candidates.find((item) => item.name === choice.model_name)
            ?.label ?? choice.model_name;
        const scopeLabel = locale.startsWith("zh")
          ? ({
              task: "本次子任务",
              turn: "仅本次主任务",
              conversation: "本对话默认模型",
            } as const)
          : ({
              task: "This subtask",
              turn: "This turn only",
              conversation: "Conversation default",
            } as const);
        setModelChoiceSummary(`${scopeLabel[choice.scope!]} · ${label}`);
      } else setModelChoiceSummary("");
      const scopedOptions = currentKnowledgeScopeSnapshot
        ? {
            ...options,
            additionalKwargs: {
              ...options?.additionalKwargs,
              [KNOWLEDGE_SCOPE_KEY]: currentKnowledgeScopeSnapshot,
            },
          }
        : options;
      if (
        choice?.scope === "turn" &&
        !modelInput.text &&
        message.files.length === 0
      ) {
        toast.info(
          locale.startsWith("zh")
            ? "请补充这次需要处理的任务。"
            : "Please include the task to run with this model.",
        );
        throw new Error("model-task-missing");
      }
      if (
        choice?.scope === "conversation" &&
        !modelInput.text &&
        message.files.length === 0
      ) {
        if (isNewThread) {
          history.replaceState(null, "", `/workspace/chats/${threadId}`);
          setThreadId(threadId);
          setIsNewThread(false);
        }
        options?.onSent?.();
        toast.success(
          locale.startsWith("zh")
            ? "已设置本对话的默认模型。"
            : "Conversation default model saved.",
        );
        return;
      }
      const executionOptions = {
        ...scopedOptions,
        additionalKwargs: {
          ...scopedOptions?.additionalKwargs,
          ...modelInput.additionalKwargs,
        },
      };
      const sendPromise = sendMessage(
        threadId,
        { ...message, text: modelInput.text },
        runModelContext,
        executionOptions,
      );
      if (message.files.length > 0) {
        return sendPromise;
      }
      void sendPromise;
    },
    [
      currentKnowledgeScopeSnapshot,
      sendMessage,
      threadId,
      ensureProjectThread,
      prepareModelControl,
      settings.context.mode,
      locale,
      isNewThread,
      projectParam,
      setThreadId,
      setIsNewThread,
    ],
  );
  const handleSubmitHumanInput = useCallback(
    async (request: HumanInputRequest, response: HumanInputResponse) => {
      let sent = false;
      await sendMessage(
        threadId,
        {
          text: buildHumanInputResponseText(request, response),
          files: [],
        },
        undefined,
        {
          additionalKwargs: {
            hide_from_ui: true,
            human_input_response: response,
            ...(currentKnowledgeScopeSnapshot
              ? { [KNOWLEDGE_SCOPE_KEY]: currentKnowledgeScopeSnapshot }
              : {}),
          },
          onSent: () => {
            sent = true;
          },
        },
      );
      return sent;
    },
    [currentKnowledgeScopeSnapshot, sendMessage, threadId],
  );
  const handleSubmitApproval = useCallback(
    (
      request: (typeof approvalRequests)[number],
      responses: Parameters<typeof submitHitlApproval>[2],
    ) => submitHitlApproval(threadId, request, responses),
    [submitHitlApproval, threadId],
  );
  const handleStop = useCallback(async () => {
    await thread.stop();
  }, [thread]);
  const handleRegenerate = useCallback(
    (messageId: string, supersededMessageIds: string[]) =>
      regenerateMessage(threadId, messageId, supersededMessageIds),
    [regenerateMessage, threadId],
  );
  const handleEditAndRegenerate = useCallback(
    (messageId: string, replacementText: string) =>
      editAndRegenerateMessage(
        threadId,
        messageId,
        replacementText,
        currentKnowledgeScopeSnapshot
          ? { [KNOWLEDGE_SCOPE_KEY]: currentKnowledgeScopeSnapshot }
          : undefined,
      ),
    [currentKnowledgeScopeSnapshot, editAndRegenerateMessage, threadId],
  );
  const handleBranchTurn = useCallback(
    async (messageId: string, messageIds: string[]) => {
      if (
        isNewThread ||
        isMock ||
        env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"
      ) {
        return;
      }

      try {
        const response = await branchThread.mutateAsync({
          threadId,
          messageId,
          messageIds,
        });
        toast.success(t.conversation.branchCreated);
        router.push(`/workspace/chats/${response.thread_id}`);
      } catch (error) {
        toast.error(
          error instanceof Error ? error.message : t.conversation.branchFailed,
        );
      }
    },
    [branchThread, isMock, isNewThread, router, t, threadId],
  );

  const hasTodos = (thread.values.todos?.length ?? 0) > 0;
  const browserEnabled = !isNewThread && !isMock && browserControlEnabled;
  const { activeGoal, hasGoal, goalOutcome, setLocalGoal } = useActiveGoal(
    threadId,
    thread.values.goal,
    thread.values.goal_outcome,
    thread.messages,
  );
  const hasOpenHumanInputCard = useMemo(
    () =>
      hasOpenHumanInputRequest(
        thread.messages,
        (message) => !isHiddenFromUIMessage(message),
      ),
    [thread.messages],
  );
  const affiliatedProjectId =
    !isNewThread && !isMock && threadMetadata.data
      ? projectIdOfThread(threadMetadata.data)
      : null;

  // A goal blocks edit-and-rerun server-side; show the pencil locked.
  const editBase =
    !isNewThread &&
    !isMock &&
    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" &&
    !isUploading &&
    !thread.isLoading &&
    !branchThread.isPending &&
    !hasOpenHumanInputCard &&
    !hasPendingApproval;

  return (
    <ThreadContext.Provider value={{ thread, isMock }}>
      <SidecarProvider
        parentThreadId={threadId}
        context={settings.context}
        isMock={isMock}
      >
        <ChatBox threadId={threadId} browserEnabled={browserEnabled}>
          <div className="relative flex size-full min-h-0 justify-between bg-[#f5f7fa]">
            {!isWelcomeMode && (
              <header className="absolute top-0 right-0 left-0 z-30 flex h-[46px] shrink-0 items-center gap-2 border-b border-[#e7ebf3] bg-white px-4">
                {!isMock && <WorkspaceSidebarTrigger className="md:hidden" />}
                <div className="flex min-w-0 flex-1 items-center gap-2 text-sm font-bold">
                  <ThreadTitle
                    threadId={threadId}
                    thread={thread}
                    canonicalTitle={threadMetadata.data?.values?.title}
                  />
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <SidecarTrigger />
                  {browserEnabled && <BrowserTrigger />}
                  <ArtifactTrigger />
                </div>
              </header>
            )}
            <main className="flex min-h-0 max-w-full grow flex-col">
              <div className="flex min-h-0 flex-1 justify-center">
                {isWelcomeMode && !hasGoal && !hasTodos ? (
                  <Welcome />
                ) : (
                  <MessageList
                    activeRunId={activeRunId}
                    activeRunStartedAt={activeRunStartedAt}
                    archiveDownloadsEnabled={
                      isNewThread || isMock || threadMetadata.data != null
                    }
                    className="size-full pt-[46px]"
                    testId="main-message-list"
                    threadId={threadId}
                    thread={thread}
                    scheduledTaskEvents={scheduledTaskEvents.data}
                    enableConversationOutline
                    paddingBottom={MESSAGE_LIST_DEFAULT_PADDING_BOTTOM}
                    hasMoreHistory={hasMoreHistory}
                    loadMoreHistory={loadMoreHistory}
                    isHistoryLoading={isHistoryLoading}
                    tokenUsageInlineMode="off"
                    approvalRequests={approvalRequests}
                    approvalMetadataLoading={
                      hasPendingApproval && approvalRequests.length === 0
                    }
                    approvalMetadataError={
                      hasPendingApproval &&
                      approvalRequests.length === 0 &&
                      threadMetadata.isError
                    }
                    onReloadApprovalMetadata={() => threadMetadata.refetch()}
                    waitingForInputRunIds={waitingForInputRunIds}
                    onSubmitApproval={handleSubmitApproval}
                    canRegenerate={
                      !isNewThread &&
                      !isMock &&
                      env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" &&
                      !isUploading &&
                      !thread.isLoading &&
                      !hasPendingApproval
                    }
                    onRegenerateMessage={handleRegenerate}
                    canEdit={editBase && !hasGoal}
                    editLockedByGoal={editBase && hasGoal}
                    onEditAndRegenerateMessage={handleEditAndRegenerate}
                    onSubmitHumanInput={
                      isMock || env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"
                        ? undefined
                        : handleSubmitHumanInput
                    }
                    canBranch={
                      !isNewThread &&
                      !isMock &&
                      env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" &&
                      !isUploading &&
                      !thread.isLoading &&
                      !branchThread.isPending &&
                      !hasPendingApproval
                    }
                    onBranchTurn={handleBranchTurn}
                  />
                )}
              </div>
              <div
                className={cn(
                  "relative right-0 bottom-0 left-0 z-30 flex shrink-0 justify-center px-4 pt-2 pb-5",
                )}
              >
                <div className={cn("relative w-full", "max-w-[820px]")}>
                  {(hasGoal || goalOutcome !== null || hasTodos) && (
                    <div className={cn("right-0 left-0 z-0", "relative")}>
                      <div
                        className={cn(
                          "right-0 bottom-0 left-0 flex flex-col",
                          "relative",
                        )}
                      >
                        <GoalStatus
                          goal={activeGoal}
                          outcome={goalOutcome}
                          isRunning={thread.isLoading}
                          hasOpenHumanInputCard={hasOpenHumanInputCard}
                          hasPendingApproval={hasPendingApproval}
                          approvalMetadataError={
                            hasPendingApproval &&
                            approvalRequests.length === 0 &&
                            threadMetadata.isError
                          }
                        />
                        {hasTodos && (
                          <TodoList
                            className="bg-background/5"
                            todos={thread.values.todos ?? []}
                            hidden={false}
                          />
                        )}
                      </div>
                    </div>
                  )}
                  {modelControl.request && (
                    <div className="mb-3" data-testid="model-selection-card">
                      <HumanInputCard
                        request={modelControl.request}
                        onSubmit={(response) => modelControl.choose(response)}
                      />
                    </div>
                  )}
                  {modelChoiceSummary && (
                    <p
                      className="text-muted-foreground mb-2 text-sm"
                      data-testid="model-selection-applied"
                    >
                      {modelChoiceSummary}
                    </p>
                  )}
                  {mountedRef.current ? (
                    <div className="w-full">
                      <ThreadRunInputs
                        inputs={runInputs}
                        threadId={isNewThread || isMock ? undefined : threadId}
                        isRunning={thread.isLoading}
                        canCreate={canCreateRuns}
                        canCancel={canStopStreaming}
                      />
                      <InputBox
                        className="w-full"
                        isWelcomeMode={isWelcomeMode}
                        threadId={threadId}
                        projectId={projectParam ?? affiliatedProjectId}
                        draftThreadId={isNewThread ? "new" : threadId}
                        knowledgeScopeControl={
                          selectorVisible && knowledgeScope ? (
                            <KnowledgeScopeSelector
                              agentName="lead_agent"
                              disabled={
                                thread.isLoading ||
                                isUploading ||
                                hasPendingApproval
                              }
                              selection={knowledgeScope}
                              onChange={setKnowledgeScope}
                            />
                          ) : undefined
                        }
                        autoFocus={isWelcomeMode}
                        status={
                          thread.error
                            ? "error"
                            : thread.isLoading
                              ? "streaming"
                              : "ready"
                        }
                        context={settings.context}
                        disabled={
                          isMock ||
                          env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ||
                          isUploading ||
                          modelControl.busy ||
                          (!isNewThread && isHistoryLoading) ||
                          hasPendingApproval
                        }
                        onContextChange={(context, options) => {
                          if (options?.automatic)
                            resolveThreadContext(threadId, context);
                          else setSettings("context", context);
                        }}
                        onGoalChange={setLocalGoal}
                        onPrepareThread={ensureProjectThread}
                        onReferenceFileAttached={() => {
                          if (!isNewThread) return;
                          history.replaceState(
                            null,
                            "",
                            `/workspace/chats/${threadId}`,
                          );
                          setThreadId(threadId);
                          setIsNewThread(false);
                        }}
                        onSubmit={handleSubmit}
                        onBusySubmit={canSendInput ? sendInput : undefined}
                        onStop={handleStop}
                        canStopStreaming={canStopStreaming}
                        canCreateRuns={canCreateRuns}
                      />
                    </div>
                  ) : (
                    <div
                      aria-hidden="true"
                      className={cn(
                        "bg-background/5 h-32 w-full rounded-2xl",
                        isWelcomeMode && "-translate-y-2 sm:-translate-y-4",
                      )}
                    />
                  )}
                  {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" && (
                    <div className="text-muted-foreground/67 w-full translate-y-12 text-center text-xs">
                      {t.common.notAvailableInDemoMode}
                    </div>
                  )}
                </div>
              </div>
            </main>
          </div>
        </ChatBox>
      </SidecarProvider>
    </ThreadContext.Provider>
  );
}
