import { FilesIcon, XIcon } from "lucide-react";
import dynamic from "next/dynamic";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  type Layout,
  type PanelSize,
  usePanelRef,
} from "react-resizable-panels";

import { ConversationEmptyState } from "@/components/ai-elements/conversation";
import { Button } from "@/components/ui/button";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  areStringArraysEqual,
  collectThreadArtifactPaths,
} from "@/core/artifacts/utils";
import { useI18n } from "@/core/i18n/hooks";
import { env } from "@/env";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";

import { useArtifacts } from "../artifacts/context";
import { useMaybeBrowserView } from "../browser-view/context";
import {
  MessageDetailsProvider,
  useMaybeMessageDetails,
} from "../message-details/context";
import { useThread } from "../messages/context";
import { useMaybeSidecar } from "../sidecar/context";

function RightPanelLoading() {
  return (
    <div className="grid size-full place-items-center rounded-2xl bg-white">
      <p role="status" className="text-sm text-[#738099]">
        正在加载预览…
      </p>
    </div>
  );
}

const ArtifactFileDetail = dynamic(
  () =>
    import("../artifacts/artifact-file-detail").then(
      (module) => module.ArtifactFileDetail,
    ),
  { loading: RightPanelLoading },
);
const ArtifactFileList = dynamic(
  () =>
    import("../artifacts/artifact-file-list").then(
      (module) => module.ArtifactFileList,
    ),
  { loading: RightPanelLoading },
);
const BrowserViewPanel = dynamic(
  () =>
    import("../browser-view/browser-view-panel").then(
      (module) => module.BrowserViewPanel,
    ),
  { loading: RightPanelLoading },
);
const SidecarPanel = dynamic(
  () =>
    import("../sidecar/sidecar-panel").then((module) => module.SidecarPanel),
  { loading: RightPanelLoading },
);

const MessageDetailsPanel = dynamic(
  () =>
    import("../message-details/message-details-panel").then(
      (module) => module.MessageDetailsPanel,
    ),
  { loading: RightPanelLoading },
);

const RIGHT_PANEL_ANIMATION_MS = 280;
const RIGHT_PANEL_DEFAULT_SIZE = "40%";

type RightPanelKind = "sidecar" | "artifacts" | "browser" | "details";

interface ChatBoxProps {
  children: React.ReactNode;
  threadId: string;
  browserEnabled?: boolean;
}

function ChatBox(props: ChatBoxProps) {
  const { setOpen: setArtifactsOpen } = useArtifacts();
  const sidecar = useMaybeSidecar();
  const browserView = useMaybeBrowserView();
  const closeOtherPanels = useCallback(() => {
    setArtifactsOpen(false);
    sidecar?.close();
    browserView?.close();
  }, [setArtifactsOpen, sidecar, browserView]);

  return (
    <MessageDetailsProvider key={props.threadId} onSelect={closeOtherPanels}>
      <ChatBoxContent {...props} />
    </MessageDetailsProvider>
  );
}

const ChatBoxContent: React.FC<ChatBoxProps> = ({
  children,
  threadId,
  browserEnabled = true,
}) => {
  const { t } = useI18n();
  const messageDetails = useMaybeMessageDetails();
  const detailsOpen = messageDetails?.open ?? false;
  const { thread } = useThread();
  const isMobile = useIsMobile();
  const pathname = usePathname();
  const threadIdRef = useRef(threadId);

  const {
    artifacts,
    open: artifactsOpen,
    setOpen: setArtifactsOpen,
    setArtifacts,
    select: selectArtifact,
    deselect,
    selectedArtifact,
  } = useArtifacts();
  const sidecar = useMaybeSidecar();
  const sidecarOpen = sidecar?.open ?? false;
  const browserView = useMaybeBrowserView();
  const browserViewOpen = browserEnabled && (browserView?.open ?? false);

  const [autoSelectFirstArtifact, setAutoSelectFirstArtifact] = useState(true);
  // A reopened thread's values carry no `artifacts` (see
  // collectThreadArtifactPaths); recover them from its present_files calls.
  const stateArtifacts = thread.values.artifacts;
  const threadArtifactPaths = useMemo(
    () =>
      collectThreadArtifactPaths(
        Array.isArray(stateArtifacts) ? stateArtifacts : [],
        thread.messages,
      ),
    [stateArtifacts, thread.messages],
  );
  useEffect(() => {
    const threadArtifacts =
      threadArtifactPaths.length > 0 ? [...threadArtifactPaths] : undefined;

    if (threadIdRef.current !== threadId) {
      threadIdRef.current = threadId;
      deselect();
    }

    // Update artifacts from the current thread
    // An empty initial state must not erase artifacts restored by the provider
    // before the persisted thread state has arrived.
    if (threadArtifacts && !areStringArraysEqual(artifacts, threadArtifacts)) {
      setArtifacts(threadArtifacts);
    }

    // DO NOT automatically deselect the artifact when switching threads, because the artifacts auto discovering is not work now.
    // if (
    //   selectedArtifact &&
    //   !thread.values.artifacts?.includes(selectedArtifact)
    // ) {
    //   deselect();
    // }

    if (
      env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" &&
      autoSelectFirstArtifact
    ) {
      if (threadArtifacts && threadArtifacts.length > 0) {
        setAutoSelectFirstArtifact(false);
        selectArtifact(threadArtifacts[0]!);
      }
    }
  }, [
    threadId,
    artifacts,
    autoSelectFirstArtifact,
    deselect,
    selectArtifact,
    selectedArtifact,
    setArtifacts,
    threadArtifactPaths,
  ]);

  const artifactPanelOpen = useMemo(() => {
    if (sidecarOpen) {
      return false;
    }
    if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true") {
      return artifactsOpen && artifacts?.length > 0;
    }
    return artifactsOpen;
  }, [artifactsOpen, artifacts, sidecarOpen]);

  const activeRightPanel: RightPanelKind | null = sidecarOpen
    ? "sidecar"
    : browserViewOpen
      ? "browser"
      : artifactPanelOpen
        ? "artifacts"
        : detailsOpen
          ? "details"
          : null;
  const rightPanelOpen = activeRightPanel !== null;
  const [renderedRightPanel, setRenderedRightPanel] =
    useState<RightPanelKind | null>(activeRightPanel);

  const resizableIdBase = useMemo(() => {
    return pathname.replace(/[^a-zA-Z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
  }, [pathname]);

  const sidePanelRef = usePanelRef();
  // Width the panel reopens at: the last size the user dragged it to.
  const openSizeRef = useRef(RIGHT_PANEL_DEFAULT_SIZE);
  // While the panel width animates, the content is held at its final width and
  // clipped instead of reflowing every frame — a reflowing message list keeps
  // re-running its scroll-to-bottom (pinned by the sidecar scroll regression
  // test), and re-wrapping text mid-animation looks unsettled. Expressed in
  // `cqw` against the group so it tracks the final width even if the group
  // itself resizes during the animation.
  const [pinnedContentWidth, setPinnedContentWidth] = useState<string | null>(
    null,
  );
  // Size transitions belong to open/close only: leaving them on during a drag
  // would interpolate every pointer frame and make the handle feel laggy.
  const [animatingRightPanel, setAnimatingRightPanel] = useState(false);
  const rightPanelOpenRef = useRef(rightPanelOpen);
  // Read once: `defaultSize` only applies on mount, the effect below owns every
  // later open/close.
  const [initialRightPanelSize] = useState(() =>
    rightPanelOpen ? RIGHT_PANEL_DEFAULT_SIZE : "0%",
  );

  const handleSidePanelResize = useCallback((size: PanelSize) => {
    if (!rightPanelOpenRef.current || size.asPercentage <= 0) {
      return;
    }
    openSizeRef.current = `${size.asPercentage}%`;
  }, []);

  const handlePanelGroupLayoutChanged = useCallback(
    (layout: Layout) => {
      if (
        !rightPanelOpenRef.current ||
        layout[`${resizableIdBase}-side`] !== 0
      ) {
        return;
      }

      // Finalize a drag-collapse only after the pointer is released. Closing
      // from onResize at the first 0% frame would break a continuous gesture
      // that reaches the edge and then reverses before release.
      if (activeRightPanel === "sidecar") {
        sidecar?.close();
      } else if (activeRightPanel === "browser") {
        browserView?.close();
      } else if (activeRightPanel === "details") {
        messageDetails?.close();
      } else if (activeRightPanel === "artifacts") {
        setArtifactsOpen(false);
      }
    },
    [
      activeRightPanel,
      browserView,
      messageDetails,
      resizableIdBase,
      setArtifactsOpen,
      sidecar,
    ],
  );

  useEffect(() => {
    if (rightPanelOpenRef.current === rightPanelOpen) {
      return;
    }
    rightPanelOpenRef.current = rightPanelOpen;

    setAnimatingRightPanel(true);
    if (!rightPanelOpen) {
      // Remember the width now: the closing animation reports shrinking sizes,
      // so sampling those would reopen the panel a few pixels wide.
      const size = sidePanelRef.current?.getSize().asPercentage ?? 0;
      if (size > 0) {
        openSizeRef.current = `${size}%`;
      }
    }

    const openPercentage = Number.parseFloat(openSizeRef.current);
    setPinnedContentWidth(
      Number.isFinite(openPercentage) ? `${openPercentage}cqw` : null,
    );

    // resize() rather than expand(): the library expands to `minSize` until it
    // has recorded a size of its own, which would reopen narrower than before.
    if (rightPanelOpen) {
      sidePanelRef.current?.resize(openSizeRef.current);
    } else {
      sidePanelRef.current?.collapse();
    }

    const timeout = window.setTimeout(() => {
      setAnimatingRightPanel(false);
      setPinnedContentWidth(null);
    }, RIGHT_PANEL_ANIMATION_MS);

    return () => {
      window.clearTimeout(timeout);
    };
  }, [rightPanelOpen, sidePanelRef]);

  useEffect(() => {
    if (activeRightPanel) {
      setRenderedRightPanel(activeRightPanel);
      return;
    }

    const timeout = window.setTimeout(() => {
      setRenderedRightPanel(null);
    }, RIGHT_PANEL_ANIMATION_MS);

    return () => {
      window.clearTimeout(timeout);
    };
  }, [activeRightPanel]);

  useEffect(() => {
    if (sidecarOpen && artifactsOpen) {
      setArtifactsOpen(false);
    }
  }, [artifactsOpen, setArtifactsOpen, sidecarOpen]);

  useEffect(() => {
    if (!browserEnabled && browserView?.open) {
      browserView.close();
    }
  }, [browserEnabled, browserView]);

  useEffect(() => {
    if (detailsOpen && (sidecarOpen || browserViewOpen || artifactPanelOpen)) {
      messageDetails?.close({ restoreFocus: false });
    }
  }, [
    detailsOpen,
    sidecarOpen,
    browserViewOpen,
    artifactPanelOpen,
    messageDetails,
  ]);

  const rightPanelContent = useMemo(() => {
    if (renderedRightPanel === "details") {
      return <MessageDetailsPanel />;
    }
    if (renderedRightPanel === "browser") {
      return <BrowserViewPanel threadId={threadId} className="size-full" />;
    }
    if (renderedRightPanel === "sidecar") {
      return <SidecarPanel />;
    }
    if (renderedRightPanel === "artifacts") {
      return (
        <div className="border-border bg-card relative flex size-full flex-col overflow-hidden rounded-xl border">
          <header className="border-border flex h-12 shrink-0 items-center border-b px-4">
            <h2 className="text-sm font-semibold">{t.common.resultArea}</h2>
          </header>
          <div className="border-border shrink-0 border-b px-4 pt-2">
            <span className="border-ring text-ring inline-flex items-center gap-1 border-b-2 px-2 pb-2 text-sm font-semibold">
              {t.common.resultArtifacts}
              <span className="text-muted-foreground text-xs font-medium">
                {artifacts.length}
              </span>
            </span>
          </div>
          <div className="absolute top-2 right-2 z-30">
            <Button
              size="icon-sm"
              variant="ghost"
              onClick={() => {
                setArtifactsOpen(false);
              }}
            >
              <XIcon />
            </Button>
          </div>
          <div className="min-h-0 grow">
            {selectedArtifact ? (
              <ArtifactFileDetail
                className="size-full"
                filepath={selectedArtifact}
                threadId={threadId}
              />
            ) : artifacts.length === 0 ? (
              <div className="grid size-full place-items-center p-4">
                <ConversationEmptyState
                  icon={<FilesIcon />}
                  title="暂未选择产物"
                  description="请从对话中的产物入口打开预览"
                />
              </div>
            ) : (
              <ScrollArea className="size-full">
                <ArtifactFileList
                  className="p-4"
                  files={artifacts}
                  threadId={threadId}
                />
              </ScrollArea>
            )}
          </div>
        </div>
      );
    }
    return null;
  }, [
    renderedRightPanel,
    selectedArtifact,
    threadId,
    artifacts,
    setArtifactsOpen,
  ]);

  if (isMobile) {
    return (
      <>
        <div className="relative size-full min-w-0">{children}</div>
        <Sheet
          open={rightPanelOpen}
          onOpenChange={(open) => {
            if (open) {
              return;
            }
            if (detailsOpen) {
              messageDetails?.close();
            }
            if (sidecarOpen) {
              sidecar?.close();
            }
            if (browserViewOpen) {
              browserView?.close();
            }
            if (artifactsOpen) {
              setArtifactsOpen(false);
            }
          }}
        >
          <SheetContent
            className="w-[calc(100vw-1rem)] max-w-none gap-0 border-[#dfe6f3] bg-[#f5f7fa] p-0 sm:max-w-md [&>button]:hidden"
            side="right"
          >
            <SheetHeader className="sr-only">
              <SheetTitle>
                {renderedRightPanel === "sidecar"
                  ? "参考资料"
                  : renderedRightPanel === "browser"
                    ? "浏览器"
                    : renderedRightPanel === "details"
                      ? (messageDetails?.selectedDetail?.title ?? t.common.more)
                      : "产物预览"}
              </SheetTitle>
              <SheetDescription>
                查看当前对话的辅助信息和产物预览。
              </SheetDescription>
            </SheetHeader>
            <div className="min-h-0 flex-1 p-3 pt-10">{rightPanelContent}</div>
          </SheetContent>
        </Sheet>
      </>
    );
  }

  return (
    <ResizablePanelGroup
      id={`${resizableIdBase}-group`}
      orientation="horizontal"
      onLayoutChanged={handlePanelGroupLayoutChanged}
      className={cn(
        "[container-type:inline-size] size-full min-h-0",
        // The sized flex item is the library's own `[data-panel]` element, not
        // the child `className` lands on, so the open/close transition has to be
        // addressed from here.
        animatingRightPanel &&
          "[&>[data-panel]]:transition-[flex-grow] [&>[data-panel]]:duration-[280ms] [&>[data-panel]]:ease-out motion-reduce:[&>[data-panel]]:transition-none",
      )}
    >
      <ResizablePanel
        id={`${resizableIdBase}-chat`}
        minSize="30%"
        className="relative min-h-0 min-w-0"
      >
        <div className="relative size-full min-h-0 min-w-0" id="chat">
          {children}
        </div>
      </ResizablePanel>
      <ResizableHandle
        id={`${resizableIdBase}-separator`}
        withHandle
        disabled={!rightPanelOpen}
        className={cn(
          "bg-[#e5eaf5] opacity-60 transition-opacity duration-200 ease-out hover:opacity-100 motion-reduce:transition-none",
          !rightPanelOpen && "pointer-events-none opacity-0",
        )}
      />
      <ResizablePanel
        id={`${resizableIdBase}-side`}
        panelRef={sidePanelRef}
        collapsible
        collapsedSize="0%"
        defaultSize={initialRightPanelSize}
        minSize="20%"
        onResize={handleSidePanelResize}
        className="min-h-0 min-w-0"
      >
        <aside
          aria-hidden={!rightPanelOpen}
          className={cn(
            "size-full min-h-0 min-w-0 overflow-hidden border-l border-[#e5eaf5] bg-[#f5f7fa] transition-opacity duration-[280ms] ease-out motion-reduce:transition-none",
            rightPanelOpen ? "opacity-100" : "pointer-events-none opacity-0",
          )}
          id="artifacts"
        >
          <div
            className={cn(
              "ml-auto h-full",
              renderedRightPanel === "artifacts" ? "p-4" : "p-0",
            )}
            style={
              pinnedContentWidth === null
                ? undefined
                : { width: pinnedContentWidth }
            }
          >
            {rightPanelContent}
          </div>
        </aside>
      </ResizablePanel>
    </ResizablePanelGroup>
  );
};

export { ChatBox };
