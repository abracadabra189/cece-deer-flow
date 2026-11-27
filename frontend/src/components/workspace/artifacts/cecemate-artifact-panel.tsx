"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  ComposerAssetIcon,
  composerFileIcon,
} from "@/components/workspace/cecemate/composer-assets";
import { urlOfArtifact } from "@/core/artifacts/utils";
import type { ArtifactEntry } from "@/core/threads/types";
import { getFileName } from "@/core/utils/files";
import { cn } from "@/lib/utils";

import { useArtifacts } from "./context";

const ASSET_ROOT = "/images/cecemate-home";

function formatArtifactCreatedAt(value: string | undefined) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function artifactLookupKeys(value: string) {
  let decoded = value;
  try {
    decoded = decodeURIComponent(value);
  } catch {
    // Keep malformed percent escapes as their literal path.
  }
  const normalized = decoded.replaceAll("\\", "/");
  return [`path:${normalized}`, `name:${getFileName(normalized)}`] as const;
}

function ArtifactActionIcon({
  name,
  className,
}: {
  name: string;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={cn("cecemate-artifact-action-icon", className)}
      style={{
        WebkitMaskImage: `url(${ASSET_ROOT}/${name})`,
        maskImage: `url(${ASSET_ROOT}/${name})`,
      }}
    />
  );
}

export function CeceMateArtifactPanel({
  artifacts,
  artifactEntries,
  artifactCreatedAtFallback,
  onClose,
  renderDetail,
  selectedArtifact,
  threadId,
}: {
  artifacts: string[];
  artifactEntries?: readonly ArtifactEntry[];
  artifactCreatedAtFallback?: ReadonlyMap<string, string>;
  onClose: () => void;
  renderDetail: (filepath: string) => ReactNode;
  selectedArtifact: string | null;
  threadId: string;
}) {
  const { returnToList, select } = useArtifacts();
  const [fullscreen, setFullscreen] = useState(false);
  const [noticeVisible, setNoticeVisible] = useState(true);
  const [openedTabs, setOpenedTabs] = useState<string[]>([]);
  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!selectedArtifact) return;
    setOpenedTabs((current) =>
      current.includes(selectedArtifact)
        ? current
        : [...current, selectedArtifact],
    );
  }, [selectedArtifact]);

  useEffect(() => {
    const available = new Set(artifacts);
    setOpenedTabs((current) => current.filter((file) => available.has(file)));
    setSelectedFiles(
      (current) => new Set([...current].filter((file) => available.has(file))),
    );
  }, [artifacts]);

  const allSelected =
    artifacts.length > 0 && selectedFiles.size === artifacts.length;
  const selectedCount = selectedFiles.size;
  const detailVisible = selectedArtifact !== null;

  const selectedDownloads = useMemo(
    () => artifacts.filter((file) => selectedFiles.has(file)),
    [artifacts, selectedFiles],
  );
  const artifactCreatedAt = useMemo(() => {
    const createdAtByKey = new Map<string, string>();
    for (const [path, createdAt] of artifactCreatedAtFallback ?? []) {
      for (const key of artifactLookupKeys(path)) {
        createdAtByKey.set(key, createdAt);
      }
    }
    for (const artifact of artifactEntries ?? []) {
      if (artifact.created_at) {
        for (const key of artifactLookupKeys(artifact.real_ref)) {
          createdAtByKey.set(key, artifact.created_at);
        }
      }
    }
    return createdAtByKey;
  }, [artifactCreatedAtFallback, artifactEntries]);
  const createdAtOfArtifact = (file: string) => {
    for (const key of artifactLookupKeys(file)) {
      const createdAt = artifactCreatedAt.get(key);
      if (createdAt) return createdAt;
    }
    return undefined;
  };

  const toggleFile = (file: string) => {
    setSelectedFiles((current) => {
      const next = new Set(current);
      if (next.has(file)) next.delete(file);
      else next.add(file);
      return next;
    });
  };

  const closeTab = (file: string) => {
    const nextTabs = openedTabs.filter((tab) => tab !== file);
    setOpenedTabs(nextTabs);
    if (selectedArtifact !== file) return;
    const fallback = nextTabs.at(-1);
    if (fallback) select(fallback);
    else returnToList();
  };

  const downloadFile = (file: string) => {
    const link = document.createElement("a");
    link.href = urlOfArtifact({ filepath: file, threadId, download: true });
    link.download = getFileName(file);
    document.body.append(link);
    link.click();
    link.remove();
  };

  return (
    <section
      className={cn(
        "cecemate-artifact-panel",
        fullscreen && "cecemate-artifact-panel-fullscreen",
      )}
    >
      <header className="cecemate-artifact-panel-header">
        {detailVisible ? (
          <div className="cecemate-artifact-tabs" role="tablist">
            {openedTabs.map((file) => (
              <div
                className="cecemate-artifact-tab"
                data-active={file === selectedArtifact}
                key={file}
                role="tab"
                aria-selected={file === selectedArtifact}
              >
                <button
                  className="cecemate-artifact-tab-select"
                  onClick={() => select(file)}
                  title={getFileName(file)}
                  type="button"
                >
                  <ComposerAssetIcon
                    name={composerFileIcon(getFileName(file))}
                    size={16}
                  />
                  <span>{getFileName(file)}</span>
                </button>
                <button
                  aria-label={`关闭 ${getFileName(file)}`}
                  className="cecemate-artifact-tab-close"
                  onClick={() => closeTab(file)}
                  type="button"
                >
                  <ArtifactActionIcon name="artifact-tab-close.svg" />
                </button>
              </div>
            ))}
          </div>
        ) : (
          <h2>所有产物</h2>
        )}
        <div className="cecemate-artifact-panel-actions">
          <button
            aria-label={fullscreen ? "退出全屏" : "全屏"}
            onClick={() => setFullscreen((value) => !value)}
            title={fullscreen ? "退出全屏" : "全屏"}
            type="button"
          >
            <ArtifactActionIcon
              name={
                fullscreen
                  ? "artifact-fullscreen-exit.svg"
                  : "artifact-fullscreen.svg"
              }
            />
          </button>
          <button
            aria-label="关闭产物区"
            onClick={onClose}
            title="关闭"
            type="button"
          >
            <ArtifactActionIcon name="artifact-close.svg" />
          </button>
        </div>
      </header>

      {detailVisible && selectedArtifact ? (
        <>
          <div className="cecemate-artifact-detail-toolbar">
            <span>{getFileName(selectedArtifact).replace(/\.[^.]+$/, "")}</span>
            <div>
              <button aria-label="引用产物" title="引用产物" type="button">
                <ArtifactActionIcon name="artifact-at.svg" />
              </button>
              <button
                aria-label="下载产物"
                onClick={() => downloadFile(selectedArtifact)}
                title="下载"
                type="button"
              >
                <ArtifactActionIcon name="artifact-download.svg" />
              </button>
            </div>
          </div>
          <div className="cecemate-artifact-detail-content">
            {renderDetail(selectedArtifact)}
          </div>
        </>
      ) : (
        <>
          {artifacts.length > 0 && (
            <div className="cecemate-artifact-selection-bar">
              <label>
                <input
                  checked={allSelected}
                  onChange={() =>
                    setSelectedFiles(
                      allSelected ? new Set() : new Set(artifacts),
                    )
                  }
                  type="checkbox"
                />
                <span>全选</span>
              </label>
              <span>
                已选中 <strong>{selectedCount}</strong> 项
              </span>
              {selectedCount > 0 && (
                <button
                  aria-label={`下载已选中的 ${selectedCount} 项产物`}
                  className="cecemate-artifact-selection-download"
                  onClick={() => selectedDownloads.forEach(downloadFile)}
                  title="下载已选产物"
                  type="button"
                >
                  <ArtifactActionIcon name="artifact-download.svg" />
                </button>
              )}
            </div>
          )}

          <div className="cecemate-artifact-list-content">
            {artifacts.length === 0 ? (
              <div className="cecemate-artifact-empty">
                <span aria-hidden="true" />
                <p>暂无产物</p>
              </div>
            ) : (
              <ul className="cecemate-artifact-file-list">
                {artifacts.map((file) => {
                  const checked = selectedFiles.has(file);
                  return (
                    <li data-checked={checked} key={file}>
                      <label
                        className="cecemate-artifact-row-checkbox"
                        onClick={(event) => event.stopPropagation()}
                      >
                        <input
                          aria-label={`选择 ${getFileName(file)}`}
                          checked={checked}
                          onChange={() => toggleFile(file)}
                          type="checkbox"
                        />
                      </label>
                      <button
                        className="cecemate-artifact-row-main"
                        onClick={() => select(file)}
                        type="button"
                      >
                        <ComposerAssetIcon
                          name={composerFileIcon(getFileName(file))}
                          size={36}
                        />
                        <span className="cecemate-artifact-row-copy">
                          <strong>{getFileName(file)}</strong>
                          <small>
                            生成时间：
                            {formatArtifactCreatedAt(createdAtOfArtifact(file))}
                          </small>
                        </span>
                      </button>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <button
                            aria-label={`${getFileName(file)} 更多操作`}
                            className="cecemate-artifact-row-more"
                            type="button"
                          >
                            <ArtifactActionIcon name="artifact-more.svg" />
                          </button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem onSelect={() => downloadFile(file)}>
                            下载
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </>
      )}

      {artifacts.length > 0 && noticeVisible && (
        <div className="cecemate-artifact-retention-notice">
          <span
            aria-label="产物文件请及时下载，30天后系统将自动清理"
            className="cecemate-artifact-retention-copy"
            role="img"
          />
          <button
            aria-label="关闭提示"
            onClick={() => setNoticeVisible(false)}
            type="button"
          >
            <ArtifactActionIcon name="artifact-notice-close.svg" />
          </button>
        </div>
      )}
    </section>
  );
}
