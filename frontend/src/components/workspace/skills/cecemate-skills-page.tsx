"use client";

import Image from "next/image";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useAuth } from "@/core/auth/AuthProvider";
import { useSkills } from "@/core/skills/hooks";
import type {
  Skill,
  SkillCatalogCategory,
  SkillReferenceCase,
} from "@/core/skills/type";
import { isSkillVisible, skillDisplayName } from "@/core/skills/visibility";
import {
  buildComposerDraftKey,
  getSessionComposerDraftStorage,
  writeComposerDraft,
  type ComposerDraftArtifactReference,
} from "@/core/threads/composer-draft";

import {
  ComposerAssetIcon,
  composerFileIcon,
} from "../cecemate/composer-assets";
import { referenceToken } from "../mentions/inline-references";
import { WorkspaceSidebarTrigger } from "../workspace-sidebar-trigger";

const ASSET_ROOT = "/images/cecemate-home";

type CatalogFilter = "all" | SkillCatalogCategory;

const catalogFilters: Array<{
  value: CatalogFilter;
  label: string;
  icon: string;
}> = [
  { value: "all", label: "全部", icon: "skills-tab-all.svg" },
  {
    value: "business_scenario",
    label: "业务场景",
    icon: "skills-tab-business.svg",
  },
  {
    value: "general_tool",
    label: "通用工具",
    icon: "skills-tab-general.svg",
  },
];

function catalogIcon(name: string) {
  return {
    WebkitMaskImage: `url(${ASSET_ROOT}/${name})`,
    maskImage: `url(${ASSET_ROOT}/${name})`,
  };
}

function skillDescription(skill: Skill) {
  return skill.display_description?.trim() || skill.description;
}

function SkillCard({
  skill,
  onSelect,
}: {
  skill: Skill;
  onSelect: (skill: Skill) => void;
}) {
  const iconPath =
    skill.icon_path?.trim() || `${ASSET_ROOT}/skill-card-default.svg`;
  return (
    <button
      className="cecemate-skill-card"
      onClick={() => onSelect(skill)}
      type="button"
    >
      <Image
        alt=""
        aria-hidden="true"
        className="cecemate-skill-card-icon"
        height={44}
        src={iconPath}
        unoptimized
        width={44}
      />
      <span className="cecemate-skill-card-copy">
        <strong>{skillDisplayName(skill)}</strong>
        <span>{skillDescription(skill)}</span>
      </span>
    </button>
  );
}

function ReferenceCase({ reference }: { reference: SkillReferenceCase }) {
  return (
    <div className="cecemate-skill-reference-case">
      <div className="cecemate-skill-reference-title">
        <span
          aria-hidden="true"
          className="cecemate-skills-section-icon"
          style={catalogIcon("skills-reference.svg")}
        />
        <strong>参考案例</strong>
        {reference.artifact_name && (
          <span className="cecemate-skill-reference-file">
            <ComposerAssetIcon
              name={composerFileIcon(reference.artifact_name)}
              size={16}
            />
            {reference.artifact_name}
          </span>
        )}
      </div>
      {reference.preview_image_path && (
        <div className="cecemate-skill-reference-preview">
          <Image
            alt={`${reference.title}预览`}
            height={360}
            src={reference.preview_image_path}
            unoptimized
            width={560}
          />
        </div>
      )}
    </div>
  );
}

export function CeceMateSkillsPage() {
  const router = useRouter();
  const { user } = useAuth();
  const { skills, isLoading, error, refetch } = useSkills();
  const [filter, setFilter] = useState<CatalogFilter>("all");
  const [selected, setSelected] = useState<Skill | null>(null);
  const catalogSkills = useMemo(
    () =>
      skills.filter(
        (skill) =>
          skill.enabled &&
          skill.category !== "integrations" &&
          isSkillVisible(skill),
      ),
    [skills],
  );
  const counts = useMemo(
    () => ({
      all: catalogSkills.length,
      business_scenario: catalogSkills.filter(
        (skill) => skill.catalog_category === "business_scenario",
      ).length,
      general_tool: catalogSkills.filter(
        (skill) => skill.catalog_category === "general_tool",
      ).length,
    }),
    [catalogSkills],
  );
  const visibleSkills = useMemo(
    () =>
      filter === "all"
        ? catalogSkills
        : catalogSkills.filter((skill) => skill.catalog_category === filter),
    [catalogSkills, filter],
  );

  const startSkill = (skill: Skill, prompt?: string | null) => {
    const artifactReferences: ComposerDraftArtifactReference[] = (
      skill.starter_references ?? []
    ).map((reference, index) => ({
      id: reference.id?.trim() || `skill:${skill.name}:reference:${index + 1}`,
      label: reference.name,
      path: reference.path,
    }));
    const skillToken = referenceToken(
      "skill",
      skill.name,
      skillDisplayName(skill),
    );
    const referenceText = artifactReferences.length
      ? `\n参考 ${artifactReferences
          .map((reference) =>
            referenceToken("artifact", reference.id, reference.label),
          )
          .join(" ")}`
      : "";
    const text = `${skillToken}${prompt?.trim() ? ` ${prompt.trim()}` : ""}${referenceText}`;
    writeComposerDraft(
      getSessionComposerDraftStorage(),
      buildComposerDraftKey({
        userId: user?.id ?? "anonymous",
        threadId: "new",
      }),
      {
        text,
        skillName: null,
        artifactReferences,
      },
    );
    router.push("/workspace/chats/new");
  };

  return (
    <main className="cecemate-skills-page">
      <header className="cecemate-skills-header">
        <WorkspaceSidebarTrigger ceceMate />
        <h1>技能</h1>
      </header>

      <div className="cecemate-skills-content">
        <nav aria-label="技能分类" className="cecemate-skills-tabs">
          {catalogFilters.map((item) => (
            <button
              aria-pressed={item.value === filter}
              data-active={item.value === filter ? "true" : undefined}
              key={item.value}
              onClick={() => setFilter(item.value)}
              type="button"
            >
              <span
                aria-hidden="true"
                className="cecemate-skills-tab-icon"
                style={catalogIcon(item.icon)}
              />
              {item.label} {counts[item.value]}
            </button>
          ))}
        </nav>

        {isLoading ? (
          <p className="cecemate-skills-state">正在读取技能…</p>
        ) : error ? (
          <div className="cecemate-skills-state" role="alert">
            <p>技能列表暂时无法读取。</p>
            <button onClick={() => void refetch()} type="button">
              重试
            </button>
          </div>
        ) : visibleSkills.length === 0 ? (
          <p className="cecemate-skills-state">暂无该分类技能</p>
        ) : (
          <section aria-label="技能列表" className="cecemate-skills-grid">
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
        <DialogContent
          className="cecemate-skill-dialog"
          showCloseButton={false}
        >
          {selected && (
            <>
              <DialogClose className="cecemate-skill-dialog-close">
                <span
                  aria-hidden="true"
                  style={catalogIcon("skills-dialog-close.svg")}
                />
                <span className="sr-only">关闭</span>
              </DialogClose>
              <DialogHeader className="cecemate-skill-dialog-header">
                <Image
                  alt=""
                  aria-hidden="true"
                  height={44}
                  src={
                    selected.icon_path?.trim() ||
                    `${ASSET_ROOT}/skill-card-default.svg`
                  }
                  unoptimized
                  width={44}
                />
                <div>
                  <DialogTitle>{skillDisplayName(selected)}</DialogTitle>
                  <DialogDescription>
                    {skillDescription(selected)}
                  </DialogDescription>
                </div>
              </DialogHeader>

              {(selected.example_queries?.length ?? 0) > 0 && (
                <section className="cecemate-skill-examples">
                  <h2>
                    <span
                      aria-hidden="true"
                      className="cecemate-skills-section-icon"
                      style={catalogIcon("skills-example.svg")}
                    />
                    使用示例
                  </h2>
                  <div>
                    {selected.example_queries!.map((query) => (
                      <button
                        key={query}
                        onClick={() => startSkill(selected, query)}
                        type="button"
                      >
                        <span>{query}</span>
                        <span
                          aria-hidden="true"
                          className="cecemate-skill-example-arrow"
                          style={catalogIcon("skills-example-arrow.svg")}
                        />
                      </button>
                    ))}
                  </div>
                </section>
              )}

              {selected.reference_cases?.[0] && (
                <ReferenceCase reference={selected.reference_cases[0]} />
              )}

              <button
                className="cecemate-skill-create-same"
                onClick={() => startSkill(selected, selected.starter_prompt)}
                type="button"
              >
                <span
                  aria-hidden="true"
                  style={catalogIcon("skills-create-same.svg")}
                />
                制作同款
              </button>
            </>
          )}
        </DialogContent>
      </Dialog>
    </main>
  );
}
