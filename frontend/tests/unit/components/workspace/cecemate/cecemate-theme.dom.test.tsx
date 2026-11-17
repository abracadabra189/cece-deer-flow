import { afterEach, expect, test } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { SidebarProvider } from "@/components/ui/sidebar";
import { CeceMateBetaItem } from "@/components/workspace/cecemate/cecemate-beta-item";
import { CeceMateBrand } from "@/components/workspace/cecemate/cecemate-brand";
import { CeceMateTheme } from "@/components/workspace/cecemate/cecemate-theme";

afterEach(cleanup);

test("scopes the CeCeMate theme and presents the Chinese brand", () => {
  render(
    <SidebarProvider>
      <CeceMateTheme>
        <CeceMateBrand />
        <CeceMateBetaItem label="MCP 服务" />
      </CeceMateTheme>
    </SidebarProvider>,
  );

  expect(
    screen.getByTestId("cecemate-theme").classList.contains("cecemate-theme"),
  ).toBe(true);
  expect(screen.getByText("CeCeMate")).toBeDefined();
  expect(screen.getByText("创投洞察 · 智能体工作台")).toBeDefined();

  const beta = screen.getByRole("button", { name: "MCP 服务 Beta" });
  expect(beta.getAttribute("aria-disabled")).toBe("true");
  expect(beta.getAttribute("disabled")).not.toBeNull();
  expect(beta.querySelector("a")).toBeNull();
});
