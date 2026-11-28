"use client";

import Image from "next/image";
import {
  CheckIcon,
  FileIcon,
  MessagesSquareIcon,
  PuzzleIcon,
  SparklesIcon,
  UploadIcon,
  XIcon,
} from "lucide-react";
import {
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type Ref,
} from "react";

import type { ConversationReference } from "@/core/conversation-references";
import type { ExtensionMention } from "@/core/extensions/contracts";
import {
  extensionMentionId,
  MAX_EXTENSION_MENTIONS,
} from "@/core/extensions/mentions";
import { useExtensionMentions } from "@/core/extensions/use-mentions";
import { useI18n } from "@/core/i18n/hooks";
import { useInfiniteProjectDocuments } from "@/core/projects/hooks";
import type { ProjectDocument } from "@/core/projects/types";
import type { Skill } from "@/core/skills/type";
import { isSkillVisible, skillDisplayName } from "@/core/skills/visibility";
import { useInfiniteThreads } from "@/core/threads/hooks";
import { agentNameOfThread, titleOfThread } from "@/core/threads/utils";
import { isCompositionConfirmEnter, isIMEComposing } from "@/lib/ime";
import { cn } from "@/lib/utils";

import { ComposerAssetIcon } from "../cecemate/composer-assets";

import { MAX_EXPLICIT_SKILLS } from "./inline-references";

export type MentionSelection =
  | { kind: "skill"; skill: Skill }
  | { kind: "file"; document: ProjectDocument }
  | { kind: "conversation"; reference: ConversationReference }
  | { kind: "extension"; reference: ExtensionMention }
  | { kind: "upload" };
export type MentionPickerHandle = {
  onKeyDown: (event: KeyboardEvent<HTMLElement>) => void;
};
type Option = {
  id: string;
  label: string;
  description?: string;
  selection: MentionSelection;
  disabled?: boolean;
  selected?: boolean;
};

function SkillCatalogIcon({ skill }: { skill: Skill }) {
  const iconPath = skill.icon_path?.trim();
  if (!iconPath) {
    return <ComposerAssetIcon name="file-skill.svg" size={16} />;
  }
  return (
    <Image
      alt=""
      aria-hidden="true"
      className="cecemate-skill-icon shrink-0 object-contain"
      height={16}
      src={iconPath}
      unoptimized
      width={16}
    />
  );
}

export function MentionPicker({
  ref,
  query,
  searchInput = false,
  skillsOnly = false,
  skills,
  skillsLoading = false,
  skillsError,
  onRetrySkills,
  capability,
  onActiveOptionChange,
  selectedSkills,
  selectedExtensions = [],
  references,
  threadId,
  projectId,
  busy,
  error,
  onSelect,
  onClose,
  listId,
  ceceMate = false,
}: {
  ref?: Ref<MentionPickerHandle>;
  query: string;
  searchInput?: boolean;
  /** The visible CeCeMate composer button opens the skill catalog only. */
  skillsOnly?: boolean;
  skills: Skill[];
  skillsLoading?: boolean;
  skillsError?: unknown;
  onRetrySkills?: () => unknown;
  capability: {
    enabled: boolean;
    maxReferences: number;
    isLoading: boolean;
    error?: unknown;
    refetch?: () => unknown;
  };
  onActiveOptionChange?: (id: string | undefined) => void;
  selectedSkills?: string[];
  selectedExtensions?: string[];
  references: ConversationReference[];
  threadId: string;
  projectId?: string | null;
  busy: boolean;
  error: string | null;
  onSelect: (selection: MentionSelection) => void;
  onClose: () => void;
  listId: string;
  ceceMate?: boolean;
}) {
  const { t } = useI18n();
  const labels = t.inputBox;
  const untitled = t.pages.untitled;
  const documents = useInfiniteProjectDocuments(projectId ?? "", {
    enabled: !skillsOnly && !!projectId,
  });
  const conversations = useInfiniteThreads(undefined, {
    enabled: !skillsOnly && capability.enabled,
  });
  const [search, setSearch] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const compositionEndedAt = useRef(-Infinity);
  const filter = (searchInput ? search : query).toLocaleLowerCase();
  const extensions = useExtensionMentions(
    searchInput ? search : query,
    threadId,
    { enabled: !skillsOnly },
  );
  const options = useMemo(() => {
    const result: Option[] = skills
      .filter((skill) => skill.enabled && isSkillVisible(skill))
      .map((skill) => ({
        id: `skill:${skill.name}`,
        label: skillDisplayName(skill),
        description: skill.description,
        selection: { kind: "skill", skill },
        selected: selectedSkills?.includes(skill.name),
        disabled:
          !selectedSkills?.includes(skill.name) &&
          new Set(selectedSkills).size >= MAX_EXPLICIT_SKILLS,
      }));
    if (!skillsOnly)
      for (const document of documents.data?.pages.flatMap(
        (page) => page.documents,
      ) ?? []) {
        result.push({
          id: `file:${document.id}`,
          label: document.name,
          description: document.content_missing
            ? labels.mentionUnavailable
            : undefined,
          selection: { kind: "file", document },
          disabled: document.content_missing,
        });
      }
    if (!skillsOnly && capability.enabled) {
      const seen = new Set<string>();
      for (const thread of conversations.data?.pages.flat() ?? []) {
        if (thread.thread_id === threadId || seen.has(thread.thread_id))
          continue;
        seen.add(thread.thread_id);
        const selected = references.some(
          (item) => item.threadId === thread.thread_id,
        );
        result.push({
          id: `conversation:${thread.thread_id}`,
          label: titleOfThread(thread, untitled),
          selection: {
            kind: "conversation",
            reference: {
              threadId: thread.thread_id,
              title: titleOfThread(thread, untitled),
              agentName: agentNameOfThread(thread),
            },
          },
          selected,
          disabled: !selected && references.length >= capability.maxReferences,
        });
      }
    }
    const filtered = result.filter((option) =>
      `${option.label} ${option.description ?? ""}`
        .toLocaleLowerCase()
        .includes(filter),
    );
    if (!skillsOnly) {
      for (const item of extensions.items) {
        const id = extensionMentionId(item);
        filtered.push({
          id: `extension:${id}`,
          label: item.label,
          description: item.description,
          selection: { kind: "extension", reference: item },
          selected: selectedExtensions.includes(id),
          disabled:
            !selectedExtensions.includes(id) &&
            new Set(selectedExtensions).size >= MAX_EXTENSION_MENTIONS,
        });
      }
      filtered.push({
        id: "upload",
        label: labels.mentionUpload,
        selection: { kind: "upload" },
      });
    }
    return filtered;
  }, [
    extensions.items,
    selectedExtensions,
    skills,
    selectedSkills,
    documents.data,
    conversations.data,
    capability.enabled,
    capability.maxReferences,
    threadId,
    references,
    filter,
    labels,
    untitled,
    skillsOnly,
  ]);
  const available = options.filter((option) => !option.disabled);
  const active =
    available.find((option) => option.id === activeId) ??
    (filter
      ? available.find((option) => option.selection.kind !== "upload")
      : available[0]);
  const optionId = (id: string) => `${listId}-${encodeURIComponent(id)}`;
  const activeOptionId = active ? optionId(active.id) : undefined;
  useEffect(() => {
    onActiveOptionChange?.(searchInput ? undefined : activeOptionId);
  }, [activeOptionId, searchInput, onActiveOptionChange]);
  useEffect(
    () => () => onActiveOptionChange?.(undefined),
    [onActiveOptionChange],
  );
  const choose = (option: Option) => {
    if (!busy && !option.disabled) onSelect(option.selection);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (isCompositionConfirmEnter(event, compositionEndedAt.current)) {
      event.preventDefault();
      return;
    }
    if (isIMEComposing(event)) return;
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const index = available.findIndex((option) => option.id === active?.id);
      const next =
        available[
          (index + (event.key === "ArrowDown" ? 1 : -1) + available.length) %
            available.length
        ];
      setActiveId(next?.id ?? null);
    } else if (event.key === "Enter" && !event.shiftKey && active) {
      event.preventDefault();
      choose(active);
    }
  };
  useImperativeHandle(ref, () => ({ onKeyDown }));
  useEffect(() => {
    if (activeOptionId)
      document
        .getElementById(activeOptionId)
        ?.scrollIntoView?.({ block: "nearest" });
  }, [activeOptionId]);
  const loading =
    (!skillsOnly && extensions.loading) ||
    skillsLoading ||
    (!skillsOnly && capability.isLoading) ||
    (!skillsOnly && !!projectId && documents.isPending) ||
    (!skillsOnly && capability.enabled && conversations.isPending);
  const failed =
    (!skillsOnly && extensions.failed) ||
    (!skillsOnly && !!capability.error) ||
    !!skillsError ||
    (!skillsOnly && !!projectId && documents.isError) ||
    (!skillsOnly && capability.enabled && conversations.isError);
  const groups = [
    { kind: "skill", title: labels.mentionSkills, Icon: SparklesIcon },
    ...(!skillsOnly
      ? ([
          { kind: "file", title: labels.mentionFiles, Icon: FileIcon },
        ] as const)
      : []),
    ...(!skillsOnly
      ? ([
          {
            kind: "conversation",
            title: labels.mentionConversations,
            Icon: MessagesSquareIcon,
          },
          {
            kind: "extension",
            title: labels.mentionExtensions,
            Icon: PuzzleIcon,
          },
          { kind: "upload", title: "", Icon: UploadIcon },
        ] as const)
      : []),
  ] as const;
  return (
    <div
      ref={rootRef}
      className={cn(
        "rounded-xl border border-[#dfe6f3] bg-white p-2 text-[#26324a] shadow-[0_8px_24px_rgb(20_32_64_/_0.12)]",
        ceceMate && "cecemate-skill-picker",
      )}
      data-testid="mention-picker"
    >
      <div
        className={cn(
          "flex items-center gap-2 px-2 pb-2",
          ceceMate && skillsOnly && "cecemate-skill-picker-heading",
        )}
      >
        {ceceMate && skillsOnly ? (
          <span>技能</span>
        ) : searchInput ? (
          <input
            aria-label={labels.mentionSearch}
            autoFocus
            className="min-w-0 flex-1 bg-transparent text-sm outline-none"
            role="combobox"
            aria-expanded="true"
            aria-controls={listId}
            aria-activedescendant={activeOptionId}
            aria-autocomplete="list"
            placeholder={labels.mentionSearch}
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setActiveId(null);
            }}
            onKeyDown={onKeyDown}
            onCompositionEnd={() => {
              compositionEndedAt.current = Date.now();
            }}
          />
        ) : (
          <span className="flex-1 text-sm font-medium">
            {labels.mentionPicker}
          </span>
        )}
        {!(ceceMate && skillsOnly) && (
          <button
            type="button"
            aria-label={labels.mentionClose}
            onClick={onClose}
          >
            <XIcon className="size-4" />
          </button>
        )}
      </div>
      <div
        id={listId}
        role="listbox"
        aria-multiselectable="true"
        aria-label={labels.mentionPicker}
        aria-busy={busy || loading}
        className={cn(
          "max-h-72 overflow-y-auto",
          ceceMate && skillsOnly && "cecemate-skill-list",
        )}
      >
        {groups.map(({ kind, title, Icon }) => {
          const items = options.filter(
            (option) => option.selection.kind === kind,
          );
          if (!items.length) return null;
          return (
            <div
              key={kind}
              role="group"
              aria-label={title ?? labels.mentionUpload}
              className={cn(
                ceceMate &&
                  skillsOnly &&
                  kind === "skill" &&
                  "cecemate-skill-group",
              )}
            >
              {title && !(ceceMate && skillsOnly) && (
                <div className="text-muted-foreground px-2 py-1 text-xs">
                  {title}
                </div>
              )}
              {items.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  role="option"
                  id={optionId(option.id)}
                  aria-selected={option.selected === true}
                  aria-disabled={busy || option.disabled}
                  disabled={busy || option.disabled}
                  onMouseDown={(event) => event.preventDefault()}
                  onMouseEnter={() => setActiveId(option.id)}
                  onClick={() => choose(option)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm disabled:opacity-40",
                    ceceMate && option.selection.kind === "skill"
                      ? "cecemate-skill-option"
                      : active?.id === option.id &&
                          "bg-[#eef3ff] text-[#2563eb]",
                  )}
                  data-active={active?.id === option.id ? "true" : undefined}
                >
                  {ceceMate && option.selection.kind === "skill" ? (
                    <SkillCatalogIcon skill={option.selection.skill} />
                  ) : (
                    <Icon className="size-4 shrink-0" />
                  )}
                  <span className="cecemate-skill-copy min-w-0 flex-1">
                    <span className="cecemate-skill-title block truncate">
                      {option.label}
                    </span>
                    {option.description && (
                      <span className="cecemate-skill-description block truncate">
                        {option.description}
                      </span>
                    )}
                  </span>
                  {option.selected &&
                    (ceceMate ? (
                      <ComposerAssetIcon name="composer-check.svg" size={14} />
                    ) : (
                      <CheckIcon className="size-4 shrink-0" />
                    ))}
                </button>
              ))}
            </div>
          );
        })}
      </div>
      {options.length === 1 && !loading && !failed && (
        <p className="text-muted-foreground px-2 py-2 text-xs">
          {labels.mentionEmpty}
        </p>
      )}
      {loading && (
        <p role="status" className="px-2 py-2 text-xs">
          {labels.mentionLoading}
        </p>
      )}
      {failed && (
        <div role="alert" className="px-2 text-xs">
          {labels.mentionFailed}{" "}
          <button
            type="button"
            onClick={() => {
              if (!skillsOnly && extensions.failed) extensions.retry();
              if (capability.error) void capability.refetch?.();
              if (skillsError) void onRetrySkills?.();
              if (!skillsOnly && projectId && documents.isError)
                void documents.refetch();
              if (!skillsOnly && capability.enabled && conversations.isError)
                void conversations.refetch();
            }}
          >
            {labels.mentionRetry}
          </button>
        </div>
      )}
      {!skillsOnly &&
        (documents.hasNextPage ||
          (capability.enabled && conversations.hasNextPage)) && (
          <button
            type="button"
            className="px-2 py-2 text-xs underline"
            disabled={
              documents.isFetchingNextPage || conversations.isFetchingNextPage
            }
            onClick={() => {
              if (documents.hasNextPage) void documents.fetchNextPage();
              if (capability.enabled && conversations.hasNextPage)
                void conversations.fetchNextPage();
            }}
          >
            {labels.mentionLoadMore}
          </button>
        )}
      {!skillsOnly && !projectId && (
        <p className="text-muted-foreground px-2 py-1 text-xs">
          {labels.mentionNoProject}
        </p>
      )}
      {!(ceceMate && skillsOnly) && (
        <p className="text-muted-foreground px-2 py-1 text-xs">
          {labels.mentionMultipleSkills}
        </p>
      )}
      {!skillsOnly && capability.enabled && (
        <p className="text-muted-foreground px-2 py-1 text-xs">
          {labels.referenceConversationsLimit(capability.maxReferences)}
        </p>
      )}
      {busy && (
        <p role="status" className="px-2 py-1 text-xs">
          {labels.mentionAttaching}
        </p>
      )}
      {error && (
        <p role="alert" className="text-destructive px-2 py-1 text-xs">
          {error}
        </p>
      )}
    </div>
  );
}
