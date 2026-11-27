import type { ConversationReference } from "@/core/conversation-references";
import {
  extensionMentionId,
  parseExtensionMention,
} from "@/core/extensions/mentions";

export const MAX_EXPLICIT_SKILLS = 16;

export type InlineReference = {
  kind:
    | "skill"
    | "file"
    | "attachment"
    | "artifact"
    | "conversation"
    | "extension";
  id: string;
  label: string;
  start: number;
  end: number;
};

export type ReferenceImagePreviewResolver = (
  reference: InlineReference,
) => string | null;

const pattern =
  /@\[([^\]]*)\]\(ref:(skill|file|attachment|artifact|conversation|extension):([^)]*)\)/g;

export function referenceToken(
  kind: InlineReference["kind"],
  id: string,
  label: string,
) {
  const encode = (value: string) =>
    encodeURIComponent(value).replace(
      /[!'()*]/g,
      (char) => `%${char.charCodeAt(0).toString(16)}`,
    );
  return `@[${encode(label)}](ref:${kind}:${encode(id)})`;
}

export function inlineReferences(text: string): InlineReference[] {
  const result: InlineReference[] = [];
  for (const match of text.matchAll(pattern)) {
    try {
      result.push({
        kind: match[2] as InlineReference["kind"],
        id: decodeURIComponent(match[3]!),
        label: decodeURIComponent(match[1]!),
        start: match.index,
        end: match.index + match[0].length,
      });
    } catch {
      /* Malformed pasted text remains ordinary text. */
    }
  }
  return result;
}

export function readableReferences(text: string) {
  let value = text;
  for (const reference of inlineReferences(text).reverse()) {
    value =
      value.slice(0, reference.start) +
      `@${reference.label}` +
      value.slice(reference.end);
  }
  return value;
}

export function textWithoutReferences(text: string) {
  let value = text;
  for (const reference of inlineReferences(text).reverse()) {
    value = value.slice(0, reference.start) + value.slice(reference.end);
  }
  return value;
}

/** Restore display labels in one pass so replacement tokens cannot match again. */
export function restoreReferenceLabels(original: string, rewritten: string) {
  const remaining = inlineReferences(original);
  if (!remaining.length) return rewritten;
  const labels = [...new Set(remaining.map((ref) => ref.label))]
    .sort((a, b) => b.length - a.length)
    .map((label) => label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  // Longest labels win; a short label cannot consume a longer word or slug.
  const pattern = new RegExp(
    `@(?:${labels.join("|")})(?![\\p{L}\\p{M}\\p{N}_-])`,
    "gu",
  );
  const restored = rewritten.replace(pattern, (label) => {
    const index = remaining.findIndex((ref) => `@${ref.label}` === label);
    if (index < 0) return label;
    const [ref] = remaining.splice(index, 1);
    return referenceToken(ref!.kind, ref!.id, ref!.label);
  });
  // A rewrite may omit a label; retain that explicit selection in draft order.
  return [
    ...remaining.map((ref) => referenceToken(ref.kind, ref.id, ref.label)),
    restored,
  ].join(" ");
}

export function readReferenceEditor(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? "";
  if (node instanceof HTMLElement) {
    if (node.dataset.reference) return node.dataset.reference;
    if (node.tagName === "BR") return "\n";
  }
  return Array.from(node.childNodes, readReferenceEditor).join("");
}

export function referenceCaret(root: HTMLElement): number | null {
  const selection = window.getSelection();
  if (!selection?.isCollapsed || !selection.rangeCount) return null;
  const range = selection.getRangeAt(0);
  if (!root.contains(range.endContainer)) return null;
  const before = range.cloneRange();
  before.selectNodeContents(root);
  before.setEnd(range.endContainer, range.endOffset);
  return readReferenceEditor(before.cloneContents()).length;
}

/** Select the adjacent object so native deletion also retains browser undo. */
export function selectReferenceForDeletion(
  root: HTMLElement,
  key: "Backspace" | "Delete",
): boolean {
  const caret = referenceCaret(root);
  if (caret === null) return false;
  for (const token of root.querySelectorAll<HTMLElement>("[data-reference]")) {
    const before = document.createRange();
    before.selectNodeContents(root);
    before.setEndBefore(token);
    const start = readReferenceEditor(before.cloneContents()).length;
    const boundary =
      key === "Backspace" ? start + token.dataset.reference!.length : start;
    if (caret !== boundary) continue;
    const range = document.createRange();
    range.selectNode(token);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    return true;
  }
  return false;
}

export function focusReferenceAt(root: HTMLElement, offset: number) {
  root.focus();
  const range = document.createRange();
  range.selectNodeContents(root);
  range.collapse(false);
  let remaining = offset;
  for (const node of root.childNodes) {
    const length = readReferenceEditor(node).length;
    if (remaining <= length) {
      if (node.nodeType === Node.TEXT_NODE) range.setStart(node, remaining);
      else if (remaining === 0) range.setStartBefore(node);
      else range.setStartAfter(node);
      range.collapse(true);
      break;
    }
    remaining -= length;
  }
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
}

function referenceFileIcon(label: string) {
  const extension = label.split(".").pop()?.toLowerCase();
  if (["doc", "docx"].includes(extension ?? "")) return "file-word.svg";
  if (extension === "pdf") return "file-pdf.svg";
  if (["xls", "xlsx", "csv"].includes(extension ?? "")) {
    return "file-excel.svg";
  }
  if (["png", "jpg", "jpeg", "gif", "webp", "svg"].includes(extension ?? "")) {
    return "file-image.svg";
  }
  if (
    ["js", "jsx", "ts", "tsx", "html", "css", "json"].includes(extension ?? "")
  ) {
    return "file-code.svg";
  }
  return "file-generic.svg";
}

export function renderReferenceEditor(
  root: HTMLElement,
  text: string,
  resolveImagePreview?: ReferenceImagePreviewResolver,
) {
  const references = inlineReferences(text);
  const previewUrls = new Map(
    references.map((reference) => [
      `${reference.kind}:${reference.id}`,
      resolveImagePreview?.(reference) ?? null,
    ]),
  );
  const previewKey = JSON.stringify([...previewUrls]);
  if (
    readReferenceEditor(root) === text &&
    root.dataset.referencePreviewKey === previewKey
  ) {
    return;
  }
  const caret = referenceCaret(root);
  const fragment = document.createDocumentFragment();
  let end = 0;
  for (const ref of references) {
    fragment.append(document.createTextNode(text.slice(end, ref.start)));
    const token = document.createElement("span");
    token.contentEditable = "false";
    token.dataset.reference = text.slice(ref.start, ref.end);
    token.dataset.referenceKind = ref.kind;
    token.dataset.testid =
      ref.kind === "file"
        ? "project-attachment-chip"
        : ref.kind === "attachment"
          ? "inline-attachment-chip"
          : ref.kind === "artifact"
            ? "artifact-reference-chip"
            : ref.kind === "conversation"
              ? "conversation-reference-chip"
              : ref.kind === "extension"
                ? "extension-mention-chip"
                : "inline-skill-reference";
    token.className =
      "cecemate-reference-chip inline-flex items-center gap-1 align-baseline font-medium select-all " +
      (ref.kind === "skill"
        ? "text-blue-600 dark:text-blue-400"
        : ref.kind === "file"
          ? "text-rose-600 dark:text-rose-400"
          : ref.kind === "attachment"
            ? "text-slate-700 dark:text-slate-300"
            : ref.kind === "artifact"
              ? "text-rose-600 dark:text-rose-400"
              : ref.kind === "extension"
                ? "text-teal-600 dark:text-teal-400"
                : "text-violet-600 dark:text-violet-400");
    const icon = document.createElement("img");
    icon.alt = "";
    icon.setAttribute("aria-hidden", "true");
    icon.className = "cecemate-reference-chip-icon";
    icon.src =
      ref.kind === "skill"
        ? "/images/cecemate-home/file-skill.svg"
        : `/images/cecemate-home/${
            ref.kind === "attachment" ||
            ref.kind === "artifact" ||
            ref.kind === "file"
              ? referenceFileIcon(ref.label)
              : "model-generic.svg"
          }`;
    const removable =
      ref.kind === "skill" ||
      ref.kind === "file" ||
      ref.kind === "attachment" ||
      ref.kind === "artifact";
    token.dataset.removable = removable ? "true" : "false";
    token.append(icon);
    if (removable) {
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "cecemate-reference-chip-remove";
      remove.setAttribute("aria-label", `移除${ref.label}`);
      const removeIcon = document.createElement("img");
      removeIcon.alt = "";
      removeIcon.src = "/images/cecemate-home/chip-remove.svg";
      remove.append(removeIcon);
      remove.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        token.remove();
        root.dispatchEvent(
          new InputEvent("input", {
            bubbles: true,
            inputType: "deleteContentBackward",
          }),
        );
        root.focus();
      });
      token.append(remove);
    }
    const label = document.createElement("span");
    label.className = "cecemate-reference-chip-label";
    label.textContent = ref.label;
    token.append(label);
    const previewUrl = previewUrls.get(`${ref.kind}:${ref.id}`);
    if (previewUrl) {
      token.dataset.imagePreview = "true";
      const preview = document.createElement("span");
      preview.className = "cecemate-reference-image-preview";
      preview.setAttribute("role", "tooltip");
      const previewImage = document.createElement("img");
      previewImage.alt = `${ref.label}预览`;
      previewImage.src = previewUrl;
      preview.append(previewImage);
      const positionImagePreview = () => {
        const tokenRect = token.getBoundingClientRect();
        const previewWidth = 280;
        const previewHeight = 261;
        const viewportPadding = 8;
        preview.style.left = `${Math.min(
          Math.max(viewportPadding, tokenRect.left),
          Math.max(
            viewportPadding,
            window.innerWidth - previewWidth - viewportPadding,
          ),
        )}px`;
        preview.style.top = `${Math.max(
          viewportPadding,
          tokenRect.top - previewHeight - 8,
        )}px`;
      };
      token.addEventListener("mouseenter", positionImagePreview);
      token.addEventListener("focusin", positionImagePreview);
      token.append(preview);
    }
    token.setAttribute("aria-label", `@${ref.label}`);
    fragment.append(token);
    end = ref.end;
  }
  fragment.append(document.createTextNode(text.slice(end)));
  root.replaceChildren(fragment);
  root.dataset.referencePreviewKey = previewKey;
  if (caret !== null) focusReferenceAt(root, Math.min(caret, text.length));
}

export function reconcileConversationReferences(
  text: string,
  known: ConversationReference[],
  capability: {
    enabled: boolean;
    maxReferences: number;
    isLoading: boolean;
    isSuccess: boolean;
  },
  threadId: string,
): { text: string; references: ConversationReference[] } {
  // Only a successful discovery may destructively normalize the draft.
  // Preserve known metadata while pending/failed, including across editor changes.
  if (!capability.isSuccess || capability.isLoading) {
    const ids = new Set(
      inlineReferences(text)
        .filter((ref) => ref.kind === "conversation")
        .map((ref) => ref.id),
    );
    return { text, references: known.filter((ref) => ids.has(ref.threadId)) };
  }
  const references = new Map<string, ConversationReference>();
  const limit = capability.enabled ? capability.maxReferences : 0;
  const tokens = inlineReferences(text).filter(
    (ref) => ref.kind === "conversation",
  );
  for (const ref of tokens) {
    if (
      !ref.id ||
      ref.id === threadId ||
      references.has(ref.id) ||
      references.size >= limit
    )
      continue;
    references.set(
      ref.id,
      known.find((item) => item.threadId === ref.id) ?? {
        threadId: ref.id,
        title: ref.label,
      },
    );
  }
  // Disabled, self, and over-limit references become honest ordinary text.
  for (const ref of tokens.reverse()) {
    if (!references.has(ref.id))
      text = text.slice(0, ref.start) + `@${ref.label}` + text.slice(ref.end);
  }
  return { text, references: [...references.values()] };
}

/** Only references still present in the draft are submitted. */
export function extensionMentionMetadata(text: string) {
  const references = new Map<
    string,
    NonNullable<ReturnType<typeof parseExtensionMention>>
  >();
  for (const ref of inlineReferences(text)) {
    if (ref.kind !== "extension") continue;
    const mention = parseExtensionMention(ref.id, ref.label);
    if (mention) references.set(extensionMentionId(mention), mention);
  }
  return references.size
    ? { extension_mentions: [...references.values()] }
    : {};
}
