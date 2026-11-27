export type SkillCatalogCategory = "business_scenario" | "general_tool";

export interface SkillReferenceCase {
  title: string;
  preview_image_path: string;
  artifact_name?: string | null;
  artifact_path?: string | null;
}

export interface SkillStarterReference {
  id?: string | null;
  name: string;
  path: string;
}

export interface Skill {
  name: string;
  display_name?: string | null;
  description: string;
  display_description?: string | null;
  example_queries?: string[];
  icon_path?: string | null;
  catalog_category?: SkillCatalogCategory | null;
  reference_cases?: SkillReferenceCase[];
  starter_prompt?: string | null;
  starter_references?: SkillStarterReference[];
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
