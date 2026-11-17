"use client";

import { BarChart3Icon, FileTextIcon, SparklesIcon } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { CeceMateLogo } from "@/components/workspace/cecemate/cecemate-brand";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

function WelcomeDescription({ children }: { children: string }) {
  return (
    <p className="max-w-full text-wrap break-words whitespace-pre-line">
      {children}
    </p>
  );
}

const examples = [
  {
    title: "企业风险监控",
    description: "跨城市产业风险识别 + 企业排查 + 风险研判，输出可溯源报告",
    prompt: "帮我写一份上海和杭州市AI算法产业的企业风险分析报告",
    tone: "bg-[#eaf0ff] text-[#2563eb]",
    Icon: BarChart3Icon,
  },
  {
    title: "半导体产业图谱",
    description: "产业链梳理 + 企业分布 + 关键环节，输出产业图谱分析",
    prompt: "请帮我做一份中国半导体产业图谱分析报告",
    tone: "bg-[#f0ecff] text-[#7b5cff]",
    Icon: SparklesIcon,
  },
  {
    title: "早期项目投资简报",
    description: "事件流监控 + 早期筛选 + 机构动向，输出投资周报",
    prompt: "最近一周具身智能的早期项目投资简报",
    tone: "bg-[#e8f8f0] text-[#12b76a]",
    Icon: FileTextIcon,
  },
] as const;

export function Welcome({
  className,
  onStartTask,
}: {
  className?: string;
  onStartTask?: (prompt: string) => Promise<void>;
}) {
  const { t } = useI18n();
  const searchParams = useSearchParams();
  const [startingPrompt, setStartingPrompt] = useState<string | null>(null);
  const isSkillMode = searchParams.get("mode") === "skill";

  const handleStartTask = async (prompt: string) => {
    if (!onStartTask || startingPrompt !== null) return;
    setStartingPrompt(prompt);
    try {
      await onStartTask(prompt);
    } catch {
      setStartingPrompt(null);
    }
  };

  return (
    <div
      className={cn(
        "mx-auto flex w-full max-w-[820px] flex-col items-center px-6 pt-[26px] pb-5 text-center",
        className,
      )}
    >
      {isSkillMode ? (
        <>
          <span className="mb-4 flex size-11 items-center justify-center rounded-2xl bg-linear-to-br from-[#2563eb] to-[#7b5cff] text-white shadow-[0_10px_26px_rgb(64_91_238_/_0.24)]">
            <SparklesIcon className="size-5" />
          </span>
          <div className="max-w-full text-2xl font-bold tracking-tight text-[#26324a]">
            技能任务
          </div>
          <div className="mt-2 max-w-full text-sm leading-6 text-[#738099]">
            <WelcomeDescription>
              {t.welcome.createYourOwnSkillDescription}
            </WelcomeDescription>
          </div>
        </>
      ) : (
        <>
          <CeceMateLogo className="size-[62px]" />
          <h1 className="mt-3 text-[21px] font-bold tracking-tight text-[#141a24]">
            Hi，我是{" "}
            <span className="bg-linear-to-br from-[#2563eb] to-[#7b5cff] bg-clip-text text-transparent">
              CeCeMate
            </span>
          </h1>
          <p className="mt-1.5 text-[13px] text-[#5a6478]">
            融合全域产业数据，AI 深度解答，生成专业报告，让复杂决策有据可依
          </p>
          <div className="mt-5 grid w-full grid-cols-1 gap-3 text-left md:grid-cols-3">
            {examples.map(({ title, description, prompt, tone, Icon }) => (
              <button
                type="button"
                key={title}
                className="min-h-[126px] rounded-xl border border-[#e7ebf3] bg-white p-3.5 text-left shadow-[0_1px_2px_rgb(20_32_64_/_0.02)] transition-[border-color,box-shadow,transform] hover:-translate-y-px hover:border-[#b9c9f8] hover:shadow-[0_8px_20px_rgb(59_91_214_/_0.10)] focus-visible:ring-2 focus-visible:ring-[#4c67f5] focus-visible:ring-offset-2 focus-visible:outline-none disabled:cursor-wait disabled:opacity-65"
                aria-label={`开始任务：${prompt}`}
                disabled={!onStartTask || startingPrompt !== null}
                onClick={() => void handleStartTask(prompt)}
              >
                <span
                  className={cn(
                    "mb-2 inline-flex rounded-md px-2 py-1 text-[11px] font-medium",
                    tone,
                  )}
                >
                  <Icon className="mr-1 size-3" />
                  {title}
                </span>
                <p className="text-[13.5px] leading-5 font-semibold text-[#141a24]">
                  {prompt}
                </p>
                <p className="mt-1 text-[11.5px] leading-[1.55] text-[#8a94a6]">
                  {description}
                </p>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
