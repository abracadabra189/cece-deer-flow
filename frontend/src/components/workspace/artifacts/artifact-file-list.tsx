import { useQuery } from "@tanstack/react-query";
import {
  ChevronRightIcon,
  DownloadIcon,
  LoaderIcon,
  PackageIcon,
} from "lucide-react";
import { useCallback, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  ArtifactRequestError,
  downloadArtifactArchive,
  getArtifactArchiveManifest,
  MAX_ARTIFACT_ARCHIVE_FILES,
} from "@/core/artifacts/api";
import { urlOfArtifact } from "@/core/artifacts/utils";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import { installSkill, SkillRequestError } from "@/core/skills/api";
import { isStaticWebsiteOnly } from "@/core/static-mode";
import {
  getFileExtensionDisplayName,
  getFileIcon,
  getFileName,
} from "@/core/utils/files";
import { cn } from "@/lib/utils";

import { useArtifacts } from "./context";

export function ArtifactFileList({
  archiveDownloadsEnabled = true,
  className,
  files,
  runId,
  threadId,
}: {
  archiveDownloadsEnabled?: boolean;
  className?: string;
  files: string[];
  runId?: string;
  threadId: string;
}) {
  const { t } = useI18n();
  const { user } = useAuth();
  const isAdmin = user?.system_role === "admin";
  const { select: selectArtifact, setOpen } = useArtifacts();
  const [downloadingArchive, setDownloadingArchive] = useState(false);
  const [installingFile, setInstallingFile] = useState<string | null>(null);
  const staticWebsiteOnly = isStaticWebsiteOnly();
  const { data: archiveManifest } = useQuery({
    queryKey: ["artifact-archive-manifest", threadId, runId],
    queryFn: () => getArtifactArchiveManifest({ threadId, runId: runId! }),
    enabled:
      archiveDownloadsEnabled && runId !== undefined && !staticWebsiteOnly,
    retry: false,
    staleTime: Infinity,
  });
  const archiveCount = archiveManifest?.fileCount;

  const handleClick = useCallback(
    (filepath: string) => {
      selectArtifact(filepath);
      setOpen(true);
    },
    [selectArtifact, setOpen],
  );

  const handleDownloadArchive = useCallback(async () => {
    if (!runId || downloadingArchive) return;

    setDownloadingArchive(true);
    let objectUrl: string | undefined;
    try {
      const { blob, filename } = await downloadArtifactArchive({
        threadId,
        runId,
      });
      objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = filename;
      document.body.append(link);
      link.click();
      link.remove();
    } catch (error) {
      console.error("Failed to download artifact archive:", error);
      toast.error(
        error instanceof ArtifactRequestError
          ? error.message
          : t.artifactArchive.downloadFailed,
      );
    } finally {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      setDownloadingArchive(false);
    }
  }, [downloadingArchive, runId, t, threadId]);

  const handleInstallSkill = useCallback(
    async (event: React.MouseEvent, filepath: string) => {
      event.stopPropagation();
      event.preventDefault();
      if (installingFile) return;

      setInstallingFile(filepath);
      try {
        const result = await installSkill({
          thread_id: threadId,
          path: filepath,
        });
        if (result.success) {
          toast.success(result.message);
        } else {
          toast.error(result.message ?? "Failed to install skill");
        }
      } catch (error) {
        console.error("Failed to install skill:", error);
        toast.error(
          error instanceof SkillRequestError && error.isAdminRequired
            ? t.settings.skills.installAdminRequired
            : "Failed to install skill",
        );
      } finally {
        setInstallingFile(null);
      }
    },
    [installingFile, t.settings.skills.installAdminRequired, threadId],
  );

  const canDownloadArchive =
    archiveDownloadsEnabled &&
    archiveCount !== undefined &&
    archiveCount > 1 &&
    archiveCount <= MAX_ARTIFACT_ARCHIVE_FILES &&
    !staticWebsiteOnly;

  return (
    <div className={cn("flex w-full flex-col gap-4", className)}>
      {canDownloadArchive && (
        <div className="flex flex-col items-start gap-1">
          <Button
            variant="outline"
            disabled={downloadingArchive}
            onClick={handleDownloadArchive}
          >
            {downloadingArchive ? (
              <LoaderIcon className="size-4 animate-spin" />
            ) : (
              <DownloadIcon className="size-4" />
            )}
            {t.artifactArchive.downloadCurrent(archiveCount)}
          </Button>
          <p className="text-muted-foreground text-xs">
            {t.artifactArchive.currentVersionNotice}
          </p>
        </div>
      )}
      <ul className="flex w-full flex-col gap-4">
        {files.map((file) => (
          <Card
            key={file}
            data-testid="result-artifact-row"
            className="group border-border bg-card hover:border-ring/50 hover:bg-accent/50 relative flex-row items-center gap-3 rounded-lg p-3 shadow-none transition-colors"
            onClick={() => handleClick(file)}
          >
            <CardHeader className="flex min-w-0 flex-1 flex-row items-center gap-3 p-0">
              <div className="bg-secondary text-foreground flex size-9 shrink-0 items-center justify-center rounded-md [&_svg]:size-5">
                {getFileIcon(file)}
              </div>
              <div className="min-w-0 flex-1">
                <CardTitle className="truncate text-sm font-semibold">
                  {getFileName(file)}
                </CardTitle>
                <CardDescription className="mt-0.5 truncate text-xs">
                  {getFileExtensionDisplayName(file)}
                </CardDescription>
              </div>
              <CardAction className="flex shrink-0 items-center gap-1 self-center">
                {file.endsWith(".skill") && isAdmin && (
                  <Button
                    aria-label={t.common.install}
                    size="icon-sm"
                    variant="ghost"
                    disabled={installingFile === file}
                    onClick={(event) => void handleInstallSkill(event, file)}
                  >
                    {installingFile === file ? (
                      <LoaderIcon className="size-4 animate-spin" />
                    ) : (
                      <PackageIcon className="size-4" />
                    )}
                    {t.common.install}
                  </Button>
                )}
                <Button size="icon-sm" variant="ghost" asChild>
                  <a
                    aria-label={`${t.common.download} ${getFileName(file)}`}
                    href={urlOfArtifact({
                      filepath: file,
                      threadId: threadId,
                      download: true,
                    })}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <DownloadIcon className="size-4" />
                  </a>
                </Button>
                <ChevronRightIcon className="text-muted-foreground size-4 transition-transform group-hover:translate-x-0.5" />
              </CardAction>
            </CardHeader>
          </Card>
        ))}
      </ul>
    </div>
  );
}
