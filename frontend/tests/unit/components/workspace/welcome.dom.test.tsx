import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { Welcome } from "@/components/workspace/welcome";
import { DEFAULT_LOCALE } from "@/core/i18n";
import { I18nProvider } from "@/core/i18n/context";

rs.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(cleanup);

describe("Welcome", () => {
  it("shows the regional industry risk description on the first task card", () => {
    render(
      <I18nProvider initialLocale={DEFAULT_LOCALE}>
        <Welcome onStartTask={async () => undefined} />
      </I18nProvider>,
    );

    expect(
      screen.getByText(
        "区域产业风险识别 + 企业排查 + 风险研判，输出可溯源报告",
      ),
    ).toBeTruthy();
    expect(
      screen.queryByText(
        "跨城市产业风险识别 + 企业排查 + 风险研判，输出可溯源报告",
      ),
    ).toBeNull();
  });
});
