export interface Skill {
  name: string;
  display_name?: string | null;
  description: string;
  category: string;
  license: string;
  enabled: boolean;
  editable: boolean;
}

export interface SkillLoadDiagnostic {
  package: string;
  path: "SKILL.md";
  code: "invalid_frontmatter";
  hint?: "quote_colon_value" | null;
  line?: number | null;
  column?: number | null;
}
