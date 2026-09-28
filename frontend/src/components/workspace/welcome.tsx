"use client";

import Image from "next/image";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo } from "react";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { AuroraText } from "../ui/aurora-text";

let waved = false;

function WelcomeDescription({ children }: { children: string }) {
  return (
    <p className="max-w-full text-wrap break-words whitespace-pre-line">
      {children}
    </p>
  );
}

export function Welcome({
  className,
  mode,
}: {
  className?: string;
  mode?: "ultra" | "pro" | "thinking" | "flash";
}) {
  const { t } = useI18n();
  const searchParams = useSearchParams();
  const isSkillMode = searchParams.get("mode") === "skill";
  const isUltra = useMemo(() => mode === "ultra", [mode]);
  const colors = useMemo(() => {
    if (isUltra) {
      return ["#efefbb", "#e9c665", "#e3a812"];
    }
    return ["var(--color-foreground)"];
  }, [isUltra]);

  useEffect(() => {
    waved = true;
  }, []);

  return (
    <div
      className={cn(
        "mx-auto flex w-full max-w-full flex-col items-center justify-center gap-2 px-4 py-4 text-center sm:px-8",
        className,
      )}
    >
      {isSkillMode ? (
        <>
          <div className="max-w-full text-2xl font-bold">
            {t.welcome.createYourOwnSkill}
          </div>
          <div className="text-muted-foreground max-w-full text-sm">
            <WelcomeDescription>
              {t.welcome.createYourOwnSkillDescription}
            </WelcomeDescription>
          </div>
        </>
      ) : (
        <div className="flex max-w-3xl items-stretch justify-center gap-4 text-left">
          <div
            className={cn(
              "flex shrink-0 items-center",
              !waved ? "animate-wave" : "",
            )}
          >
            <Image
              src="/images/welcome-greeting.png"
              alt="Welcome"
              width={72}
              height={72}
              priority
              className="h-full w-auto object-contain"
            />
          </div>
          <div className="flex min-w-0 flex-col justify-center gap-1">
            <div className="flex flex-wrap items-center gap-3 text-2xl font-bold">
              <AuroraText colors={colors}>{"hi,\u6211\u662f"}</AuroraText>
              <Image
                src="/images/CECE.svg"
                alt="CECE"
                width={160}
                height={48}
                priority
                className="h-[1em] w-auto object-contain"
              />
            </div>
            <div className="text-muted-foreground max-w-full text-sm">
              <WelcomeDescription>{t.welcome.description}</WelcomeDescription>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
