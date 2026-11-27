import { PanelRightCloseIcon, PanelRightOpenIcon } from "lucide-react";
import Image from "next/image";

import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/workspace/tooltip";
import { useI18n } from "@/core/i18n/hooks";

import { useMaybeSidecar } from "../sidecar/context";

import { useArtifacts } from "./context";

export const ArtifactTrigger = ({
  ceceMate = false,
}: {
  ceceMate?: boolean;
}) => {
  const { t } = useI18n();
  const {
    artifacts,
    open: artifactsOpen,
    deselect,
    setOpen: setArtifactsOpen,
  } = useArtifacts();
  const sidecar = useMaybeSidecar();
  const resultAreaOpen = artifactsOpen && !(sidecar?.open ?? false);
  const label = resultAreaOpen
    ? t.common.collapseResultArea
    : t.common.showResultArea;

  if ((!artifacts || artifacts.length === 0) && !ceceMate) {
    return null;
  }
  return (
    <Tooltip content={label}>
      <Button
        aria-label={label}
        className={
          ceceMate
            ? "cecemate-artifact-trigger"
            : "border-ring/50 bg-ring hover:bg-ring/90 rounded-xl border text-white shadow-sm hover:text-white"
        }
        size={ceceMate ? "icon-sm" : "default"}
        variant="ghost"
        data-testid="artifact-trigger"
        onClick={() => {
          if (resultAreaOpen) {
            setArtifactsOpen(false);
            return;
          }
          sidecar?.close();
          deselect();
          setArtifactsOpen(true);
        }}
      >
        {ceceMate ? (
          <Image
            alt=""
            aria-hidden="true"
            className="cecemate-chat-artifact-trigger-icon"
            height={16}
            src="/images/cecemate-home/chat-artifacts-toggle.svg"
            width={16}
          />
        ) : (
          <>
            {resultAreaOpen ? <PanelRightCloseIcon /> : <PanelRightOpenIcon />}
            <span className="hidden sm:inline">
              {resultAreaOpen
                ? t.common.collapseResultArea
                : t.common.resultArea}
            </span>
          </>
        )}
      </Button>
    </Tooltip>
  );
};
