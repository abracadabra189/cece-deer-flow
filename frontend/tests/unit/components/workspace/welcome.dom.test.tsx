import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { Welcome, WelcomeExamples } from "@/components/workspace/welcome";
import { DEFAULT_LOCALE } from "@/core/i18n";
import { I18nProvider } from "@/core/i18n/context";

rs.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(cleanup);

describe("Welcome", () => {
  it("starts the selected example task", () => {
    const start = rs.fn(async () => undefined);
    render(
      <I18nProvider initialLocale={DEFAULT_LOCALE}>
        <Welcome />
        <WelcomeExamples onStartTask={start} />
      </I18nProvider>,
    );

    expect(screen.getByRole("heading", { name: /CeCeMate/ })).toBeTruthy();
    expect(screen.getAllByRole("button")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: /商机清单/ }));
    expect(start).toHaveBeenCalledWith(
      "上海人工智能产业有哪些重点企业？主要分布在哪些园区？",
    );
  });
});
