import { FilesIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/workspace/tooltip";
import { useI18n } from "@/core/i18n/hooks";

import { useMaybeSidecar } from "../sidecar/context";

import { useArtifacts } from "./context";

export const ArtifactTrigger = () => {
  const { t } = useI18n();
  const { artifacts, deselect, setOpen: setArtifactsOpen } = useArtifacts();
  const sidecar = useMaybeSidecar();

  if (!artifacts || artifacts.length === 0) {
    return null;
  }
  return (
    <Tooltip content={t.common.showResultArea}>
      <Button
        aria-label={t.common.showResultArea}
        className="border-ring/50 bg-ring hover:bg-ring/90 rounded-xl border text-white shadow-sm hover:text-white"
        variant="ghost"
        data-testid="artifact-trigger"
        onClick={() => {
          sidecar?.close();
          deselect();
          setArtifactsOpen(true);
        }}
      >
        <FilesIcon />
        <span className="hidden sm:inline">{t.common.resultArea}</span>
      </Button>
    </Tooltip>
  );
};
