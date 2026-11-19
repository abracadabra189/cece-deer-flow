"use client";

import { useEffect, useState } from "react";

import { Shimmer } from "@/components/ai-elements/shimmer";
import { useI18n } from "@/core/i18n/hooks";
import { formatRunDuration } from "@/core/messages/run-duration";
import { cn } from "@/lib/utils";

export function RunActivity({ startTime }: { startTime: number | null }) {
  const { t } = useI18n();
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (startTime === null) {
      return;
    }

    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [startTime]);

  const elapsedSeconds =
    startTime === null ? 0 : Math.max(0, Math.floor((now - startTime) / 1000));
  const formatted =
    elapsedSeconds === 0
      ? "0s"
      : (formatRunDuration(elapsedSeconds, t.runDuration) ?? "");

  return (
    <div
      className="text-muted-foreground flex items-center gap-2 text-sm"
      data-testid="run-activity"
    >
      <Shimmer
        duration={1}
      >{`${t.runDuration.working} (${formatted})`}</Shimmer>
    </div>
  );
}

export function RunDurationLabel({
  durationSeconds,
  className,
}: {
  durationSeconds: number;
  className?: string;
}) {
  const { t } = useI18n();
  const formatted = formatRunDuration(durationSeconds, t.runDuration);
  if (!formatted) {
    return null;
  }

  return (
    <span
      className={className}
      data-testid="run-duration"
      title={t.runDuration.description}
    >
      {t.runDuration.completedIn(formatted)}
    </span>
  );
}

export function RunDuration({
  durationSeconds,
  revealOnHover = false,
}: {
  durationSeconds: number;
  revealOnHover?: boolean;
}) {
  return (
    <div
      className={cn(
        "text-muted-foreground border-border/60 mb-3 border-b pb-3 text-sm",
        revealOnHover &&
          "invisible h-0 overflow-hidden border-b-0 pb-0 opacity-0 transition-[height,opacity,margin] group-hover/run-duration:visible group-hover/run-duration:mb-3 group-hover/run-duration:h-auto group-hover/run-duration:border-b group-hover/run-duration:pb-3 group-hover/run-duration:opacity-100",
      )}
    >
      <RunDurationLabel durationSeconds={durationSeconds} />
    </div>
  );
}
