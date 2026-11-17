import { afterEach, expect, rs, test } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { CeceMateSkillsPage } from "@/components/workspace/skills/cecemate-skills-page";

const refetch = rs.fn();
rs.mock("@/core/skills/hooks", () => ({
  useSkills: () => ({
    skills: [
      {
        name: "deep-research",
        description: "Research across sources",
        category: "public",
        license: "MIT",
        enabled: true,
        editable: false,
      },
      {
        name: "private-analysis",
        description: "Internal analysis",
        category: "custom",
        license: "Proprietary",
        enabled: false,
        editable: false,
      },
    ],
    isLoading: false,
    error: null,
    refetch,
  }),
}));

afterEach(cleanup);

test("renders real skills as a Chinese read-only catalog", () => {
  render(<CeceMateSkillsPage />);

  expect(
    screen.getByRole("heading", { name: "为任务选择合适的技能" }),
  ).toBeDefined();
  expect(screen.getByText("深度研究")).toBeDefined();
  expect(screen.getByText("private-analysis")).toBeDefined();
  expect(screen.getByText("可使用")).toBeDefined();
  expect(screen.getByText("暂不可用")).toBeDefined();

  fireEvent.change(screen.getByRole("textbox", { name: "搜索技能" }), {
    target: { value: "private" },
  });
  expect(screen.queryByText("深度研究")).toBeNull();
  expect(screen.getByText("private-analysis")).toBeDefined();

  fireEvent.click(screen.getByText("private-analysis"));
  const dialog = screen.getByRole("dialog");
  expect(dialog).toBeDefined();
  expect(dialog.textContent).toContain("Internal analysis");

  for (const label of ["上传", "安装", "编辑", "删除", "启用", "停用"]) {
    expect(screen.queryByRole("button", { name: label })).toBeNull();
  }
});
