import Image from "next/image";

import type { Model } from "@/core/models/types";

import { cn } from "@/lib/utils";

export const CECE_COMPOSER_ASSET_ROOT = "/images/cecemate-home";

export type ComposerAssetName =
  | "chevron-down.svg"
  | "chip-remove.svg"
  | "composer-add.svg"
  | "composer-artifact.svg"
  | "composer-check.svg"
  | "composer-polish-undo.svg"
  | "composer-polish.svg"
  | "composer-skill.svg"
  | "composer-upload.svg"
  | "file-code.svg"
  | "file-excel.svg"
  | "file-generic.svg"
  | "file-image.svg"
  | "file-pdf.svg"
  | "file-ppt.svg"
  | "file-skill.svg"
  | "file-word.svg"
  | "mode-fast.svg"
  | "mode-research.svg"
  | "mode-thinking.svg"
  | "model-deepseek.svg"
  | "model-generic.svg"
  | "model-glm.svg"
  | "model-qwen.svg";

export function ComposerAssetIcon({
  name,
  size = 16,
  className,
}: {
  name: ComposerAssetName;
  size?: number;
  className?: string;
}) {
  return (
    <Image
      alt=""
      aria-hidden="true"
      className={cn("shrink-0 object-contain", className)}
      height={size}
      src={`${CECE_COMPOSER_ASSET_ROOT}/${name}`}
      width={size}
    />
  );
}

export function composerFileIcon(filename: string): ComposerAssetName {
  const extension = filename.split(".").pop()?.toLowerCase();
  if (["doc", "docx"].includes(extension ?? "")) return "file-word.svg";
  if (extension === "pdf") return "file-pdf.svg";
  if (["ppt", "pptx"].includes(extension ?? "")) return "file-ppt.svg";
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

export function composerModelIcon(model?: Model): ComposerAssetName {
  const identity =
    `${model?.provider ?? ""} ${model?.name ?? ""} ${model?.model ?? ""}`.toLowerCase();
  if (identity.includes("deepseek")) return "model-deepseek.svg";
  if (identity.includes("qwen")) return "model-qwen.svg";
  if (identity.includes("glm")) return "model-glm.svg";
  return "model-generic.svg";
}

export function composerModelTags(model: Model): string[] {
  const catalogTags = model.tags
    ?.map((tag) => tag.trim())
    .filter((tag) => tag.length > 0);
  if (catalogTags?.length) return catalogTags;

  const catalogTag = model.tag?.trim();
  if (catalogTag) return [catalogTag];

  const identifiers = [model.display_name, model.name, model.model].map(
    (value) => value.trim().toLowerCase(),
  );
  const matches = (...names: string[]) =>
    identifiers.some((identifier) => names.includes(identifier));

  if (matches("deepseek v4.1 flash", "deepseek-v4.1-flash")) {
    return ["默认", "报告生成"];
  }
  if (matches("qwen4 max", "qwen4_max")) return ["复杂任务"];
  if (matches("qwen3.8-flash", "qwen3.8 flash")) {
    return ["速度最快", "问数"];
  }
  if (matches("glm-5.3-flash", "glm-5.3 flash")) return ["HTML生成"];
  if (matches("qwen4-max")) return ["截图分析", "文件分析"];
  return [];
}
