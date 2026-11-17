import {
  ChartNoAxesCombinedIcon,
  CodeIcon,
  SearchIcon,
  type LucideIcon,
} from "lucide-react";

import type { Skill } from "@/core/skills/type";
import { skillDisplayName } from "@/core/skills/visibility";

// Curated card summaries, not copies of the runtime skill descriptions.
// Keep keys aligned with skills/public; the catalog contract test checks this.
export const builtinSkillPresentation: Readonly<
  Record<string, { title: string; description: string; icon: LucideIcon }>
> = {
  "deep-research": {
    title: "深度研究",
    description: "围绕复杂问题检索、交叉验证资料，整理成有据可查的研究报告。",
    icon: SearchIcon,
  },
  "data-analysis": {
    title: "数据分析",
    description: "分析表格与结构化数据，发现规律，并用图表清晰呈现结论。",
    icon: ChartNoAxesCombinedIcon,
  },
  "frontend-design": {
    title: "前端设计",
    description: "设计并实现网页与交互界面，兼顾视觉表达和实际使用体验。",
    icon: CodeIcon,
  },
};

const chineseDescriptionOverrides: Readonly<Record<string, string>> = {
  "chart-visualization": "将数据转换为清晰直观的可视化图表。",
  "consulting-analysis": "生成结构化的专业咨询分析报告。",
  "web-design-guidelines": "提供清晰、一致且易用的网页设计建议。",
};

export function presentSkill(skill: Skill, locale: string) {
  const presentation =
    skill.category === "public" &&
    Object.hasOwn(builtinSkillPresentation, skill.name)
      ? builtinSkillPresentation[skill.name]
      : undefined;
  const chineseDescription = Object.hasOwn(
    chineseDescriptionOverrides,
    skill.name,
  )
    ? chineseDescriptionOverrides[skill.name]
    : undefined;
  return {
    title: skill.display_name?.trim().length
      ? skillDisplayName(skill)
      : locale === "zh-CN" && presentation
        ? presentation.title
        : skill.name,
    description:
      locale === "zh-CN"
        ? (chineseDescription ?? presentation?.description ?? skill.description)
        : skill.description,
    icon: presentation?.icon,
  };
}
