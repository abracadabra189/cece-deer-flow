"use client";

import { SearchIcon, SparklesIcon } from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useSkills } from "@/core/skills/hooks";
import type { Skill } from "@/core/skills/type";
import { cn } from "@/lib/utils";

import { presentSkill } from "../capabilities/skill-presentation";

const allCategories = "全部";

function SkillCard({
  skill,
  onSelect,
}: {
  skill: Skill;
  onSelect: (skill: Skill) => void;
}) {
  const presentation = presentSkill(skill, "zh-CN");
  const Icon = presentation.icon ?? SparklesIcon;
  return (
    <button
      className="group relative flex min-h-48 flex-col rounded-2xl border border-[#e5eaf5] bg-white p-5 text-left shadow-[0_8px_24px_rgb(44_70_128_/_0.05)] transition-all hover:-translate-y-0.5 hover:border-[#b9c9ff] hover:shadow-[0_14px_30px_rgb(37_99_235_/_0.12)] focus-visible:ring-2 focus-visible:ring-[#2563eb] focus-visible:outline-none"
      onClick={() => onSelect(skill)}
      type="button"
    >
      <div className="mb-5 flex items-start justify-between gap-3">
        <span className="flex size-10 items-center justify-center rounded-xl bg-[#eef3ff] text-[#2563eb]">
          <Icon className="size-5" />
        </span>
        <span
          className={cn(
            "rounded-full px-2 py-1 text-[11px] font-medium",
            skill.enabled
              ? "bg-[#ecfdf3] text-[#16804b]"
              : "bg-[#f3f4f6] text-[#7c8595]",
          )}
        >
          {skill.enabled ? "可使用" : "暂不可用"}
        </span>
      </div>
      <h2 className="text-[15px] font-semibold text-[#26324a]">
        {presentation.title}
      </h2>
      <p className="mt-2 line-clamp-3 text-sm leading-6 text-[#738099]">
        {presentation.description || "暂未提供技能说明。"}
      </p>
      <span className="mt-auto pt-4 text-xs font-medium text-[#7b5cff]">
        {skill.category || "未分类"}
      </span>
    </button>
  );
}

export function CeceMateSkillsPage() {
  const { skills, isLoading, error, refetch } = useSkills();
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState(allCategories);
  const [selected, setSelected] = useState<Skill | null>(null);
  const catalogSkills = useMemo(
    () => skills.filter((skill) => skill.category !== "integrations"),
    [skills],
  );
  const categories = useMemo(
    () => [
      allCategories,
      ...new Set(catalogSkills.map((skill) => skill.category)),
    ],
    [catalogSkills],
  );
  const visibleSkills = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return catalogSkills.filter((skill) => {
      const presentation = presentSkill(skill, "zh-CN");
      return (
        (category === allCategories || skill.category === category) &&
        (!normalized ||
          `${presentation.title} ${presentation.description} ${skill.name}`
            .toLocaleLowerCase()
            .includes(normalized))
      );
    });
  }, [category, query, catalogSkills]);

  return (
    <main className="min-h-full w-full bg-[#f5f7fa] px-5 py-8 sm:px-8 lg:px-12">
      <div className="mx-auto max-w-6xl">
        <header className="mb-8 flex flex-col justify-between gap-5 border-b border-[#e5eaf5] pb-6 sm:flex-row sm:items-end">
          <div>
            <span className="inline-flex items-center gap-1.5 text-xs font-semibold tracking-[0.14em] text-[#7b5cff]">
              <SparklesIcon className="size-3.5" /> 技能中心
            </span>
            <h1 className="mt-2 text-2xl font-bold tracking-tight text-[#26324a]">
              为任务选择合适的技能
            </h1>
          </div>
          <label className="relative block w-full sm:w-72">
            <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-[#8a94a6]" />
            <Input
              aria-label="搜索技能"
              className="h-10 rounded-xl border-[#dfe6f3] bg-white pl-9 shadow-sm"
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索技能"
              value={query}
            />
          </label>
        </header>

        <div aria-label="技能分类" className="mb-6 flex flex-wrap gap-2">
          {categories.map((item) => (
            <Button
              aria-pressed={item === category}
              className={cn(
                "h-8 rounded-full border px-3 text-xs shadow-none",
                item === category
                  ? "border-[#2563eb] bg-[#2563eb] text-white hover:bg-[#1d4ed8]"
                  : "border-[#dfe6f3] bg-white text-[#65718a] hover:bg-[#eef3ff] hover:text-[#2563eb]",
              )}
              key={item}
              onClick={() => setCategory(item)}
              type="button"
              variant="outline"
            >
              {item}
            </Button>
          ))}
        </div>

        {isLoading ? (
          <p className="rounded-2xl border border-dashed border-[#dfe6f3] bg-white px-5 py-10 text-center text-sm text-[#738099]">
            正在读取技能…
          </p>
        ) : error ? (
          <div className="rounded-2xl border border-[#fde0e0] bg-white px-5 py-10 text-center">
            <p className="text-sm text-[#b54747]">技能列表暂时无法读取。</p>
            <Button
              className="mt-4"
              onClick={() => void refetch()}
              type="button"
            >
              重试
            </Button>
          </div>
        ) : visibleSkills.length === 0 ? (
          <p className="rounded-2xl border border-dashed border-[#dfe6f3] bg-white px-5 py-10 text-center text-sm text-[#738099]">
            没有符合条件的技能。
          </p>
        ) : (
          <section
            aria-label="技能列表"
            className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3"
          >
            {visibleSkills.map((skill) => (
              <SkillCard
                key={skill.name}
                skill={skill}
                onSelect={setSelected}
              />
            ))}
          </section>
        )}
      </div>

      <Dialog
        open={selected !== null}
        onOpenChange={(open) => !open && setSelected(null)}
      >
        <DialogContent className="max-w-md rounded-2xl border-[#dfe6f3] bg-white">
          {selected &&
            (() => {
              const presentation = presentSkill(selected, "zh-CN");
              return (
                <>
                  <DialogHeader>
                    <DialogTitle>{presentation.title}</DialogTitle>
                    <DialogDescription className="leading-6">
                      {presentation.description || "暂未提供技能说明。"}
                    </DialogDescription>
                  </DialogHeader>
                  <dl className="grid grid-cols-[72px_1fr] gap-x-3 gap-y-3 text-sm">
                    <dt className="text-[#8a94a6]">分类</dt>
                    <dd>{selected.category || "未分类"}</dd>
                    <dt className="text-[#8a94a6]">状态</dt>
                    <dd>{selected.enabled ? "可使用" : "暂不可用"}</dd>
                    <dt className="text-[#8a94a6]">许可</dt>
                    <dd>{selected.license || "未提供"}</dd>
                  </dl>
                </>
              );
            })()}
        </DialogContent>
      </Dialog>
    </main>
  );
}
