"use client";

import { SparklesIcon } from "lucide-react";
import Image from "next/image";
import { useState } from "react";

import { useI18n } from "@/core/i18n/hooks";

const assetRoot = "/images/cecemate-home";
const examples = [
  {
    title: "产业分析一页纸",
    tag: "一页纸",
    image: "industry",
    prompt:
      "上海半导体产业链全景分析一页纸：\n产业链构成、产业发展水平、头部企业",
  },
  {
    title: "商机清单",
    tag: "问数",
    image: "opportunities",
    prompt: "上海人工智能产业有哪些重点企业？主要分布在哪些园区？",
  },
  {
    title: "企业风险扫描",
    tag: "报告",
    image: "risk",
    prompt: "最近一周新能源产业的企业\n风险监测简报",
  },
] as const;

export function Welcome({ skillMode = false }: { skillMode?: boolean }) {
  const { t } = useI18n();
  if (skillMode)
    return (
      <div className="mx-auto flex flex-col items-center px-6 pt-7 text-center">
        <span className="mb-4 flex size-11 items-center justify-center rounded-2xl bg-linear-to-br from-[#2563eb] to-[#7b5cff] text-white shadow-[0_10px_26px_rgb(64_91_238_/_0.24)]">
          <SparklesIcon className="size-5" />
        </span>
        <div className="max-w-full text-2xl font-bold tracking-tight text-[#26324a]">
          技能任务
        </div>
        <div className="mt-2 max-w-full text-sm leading-6 text-[#738099]">
          <p>{t.welcome.createYourOwnSkillDescription}</p>
        </div>
      </div>
    );
  return (
    <header className="home-greeting">
      <span className="home-avatar" aria-hidden="true" />
      <div>
        <h1 aria-label="Hi, 我是 CeCeMate">
          <Image
            src={`${assetRoot}/greeting-hi-im.svg`}
            alt=""
            aria-hidden="true"
            width={129}
            height={32}
          />
          <Image
            src={`${assetRoot}/greeting-cecemate.svg`}
            alt=""
            aria-hidden="true"
            width={190}
            height={32}
          />
        </h1>
        <p>融合全域产业数据，AI深度解答，生成专业报告，让复杂决策有据可依</p>
      </div>
    </header>
  );
}

export function WelcomeExamples({
  onStartTask,
}: {
  onStartTask: (prompt: string) => Promise<void>;
}) {
  const [starting, setStarting] = useState(false);
  async function start(prompt: string) {
    if (starting) return;
    setStarting(true);
    try {
      await onStartTask(prompt.replaceAll("\n", ""));
    } catch {
      setStarting(false);
    }
  }
  return (
    <div className="home-examples">
      {examples.map(({ title, image, tag, prompt }) => (
        <button
          type="button"
          key={image}
          disabled={starting}
          onClick={() => void start(prompt)}
        >
          <span
            className="home-card-image"
            aria-hidden="true"
            style={{ backgroundImage: `url(${assetRoot}/card-${image}.png)` }}
          />
          <div>
            <strong>
              {title}
              <small data-tone={image}>{tag}</small>
            </strong>
            <p>{prompt}</p>
          </div>
        </button>
      ))}
    </div>
  );
}
