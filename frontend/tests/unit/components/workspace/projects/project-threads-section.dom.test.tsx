import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render } from "@testing-library/react";
import type { PropsWithChildren } from "react";

import { ProjectThreadsSection } from "@/components/workspace/projects/project-threads-section";
import { I18nProvider } from "@/core/i18n/context";
import type { ProjectThreadsQueryResult } from "@/core/projects";
import type { ProjectThread } from "@/core/projects/types";

// Keep the row links inert under happy-dom; only the href wiring matters.
rs.mock("next/link", () => {
  const MockLink = ({
    href,
    children,
    ...props
  }: {
    href: string;
    children: React.ReactNode;
  } & React.ComponentProps<"a">) => (
    <a href={href} {...props}>
      {children}
    </a>
  );
  return { default: MockLink };
});

function makeThread(id: string, title: string): ProjectThread {
  return {
    thread_id: id,
    display_name: title,
    metadata: {},
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
  };
}

function makeQuery(threads: ProjectThread[]): ProjectThreadsQueryResult {
  return {
    data: { pages: [threads], pageParams: [0] },
    isError: false,
    isLoading: false,
    hasNextPage: false,
    isFetchingNextPage: false,
    fetchNextPage: rs.fn(),
  } as unknown as ProjectThreadsQueryResult;
}

function Wrapper({ children }: PropsWithChildren) {
  return <I18nProvider initialLocale="en-US">{children}</I18nProvider>;
}

afterEach(() => {
  cleanup();
});

describe("ProjectThreadsSection", () => {
  it("renders prototype-style task cards with the real task title and update time", () => {
    const { container } = render(
      <Wrapper>
        <ProjectThreadsSection
          query={makeQuery([
            makeThread("t-1", "First"),
            makeThread("t-2", "Second"),
            makeThread("t-3", "Third"),
          ])}
        />
      </Wrapper>,
    );

    const links = container.querySelectorAll<HTMLAnchorElement>("a");
    expect(links).toHaveLength(3);
    expect(links[0]?.href).toContain("/workspace/chats/t-1");
    const firstRow = container.querySelector(
      '[data-testid="project-task-row"]',
    );
    expect(firstRow).not.toBeNull();
    expect(firstRow?.classList.contains("rounded-xl")).toBe(true);
    expect(firstRow?.classList.contains("border")).toBe(true);
    expect(firstRow?.textContent).toContain("First");
    expect(firstRow?.textContent).toContain("ago");
  });

  it("shows the untitled fallback and the load-more button for a partial page", () => {
    const { container } = render(
      <Wrapper>
        <ProjectThreadsSection
          query={
            {
              data: {
                pages: [[makeThread("t-1", "  ")]],
                pageParams: [0],
              },
              isError: false,
              isLoading: false,
              hasNextPage: true,
              isFetchingNextPage: false,
              fetchNextPage: rs.fn(),
            } as unknown as ProjectThreadsQueryResult
          }
        />
      </Wrapper>,
    );

    expect(container.textContent).toContain("Untitled");
    expect(
      container.querySelector('[data-testid="project-threads-load-more"]'),
    ).not.toBeNull();
  });
});
