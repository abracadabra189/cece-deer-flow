import type { Skill } from "./type";

const HIDDEN_CATALOG_SKILL_NAMES = new Set(["enterprise-qa", "cece-hydc-data"]);

/** Whether a skill is shown in user-facing catalogs and composer pickers. */
export function isSkillVisible(skill: Pick<Skill, "name">): boolean {
  return !HIDDEN_CATALOG_SKILL_NAMES.has(skill.name);
}

/** Return the validated human-facing title, falling back to the stable ID. */
export function skillDisplayName(
  skill: Pick<Skill, "name" | "display_name">,
): string {
  const displayName = skill.display_name?.trim();
  return displayName ?? skill.name;
}
