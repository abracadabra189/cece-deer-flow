import { describe, expect, it } from "@rstest/core";

import type { Skill } from "@/core/skills/type";
import { isSkillVisible } from "@/core/skills/visibility";

function skill(name: string): Skill {
  return {
    name,
    description: "Description",
    category: "public",
    license: "MIT",
    enabled: true,
    editable: false,
  };
}

describe("skill catalog visibility", () => {
  it.each(["enterprise-qa", "cece-hydc-data"])(
    "hides %s from user-facing skill catalogs",
    (name) => expect(isSkillVisible(skill(name))).toBe(false),
  );

  it("keeps ordinary skills visible", () => {
    expect(isSkillVisible(skill("deep-research"))).toBe(true);
  });
});
