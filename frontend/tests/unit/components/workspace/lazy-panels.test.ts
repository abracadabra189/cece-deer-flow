import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "@rstest/core";

const FRONTEND_ROOT = path.resolve(__dirname, "../../../..");
const read = (relativePath: string) =>
  readFileSync(path.join(FRONTEND_ROOT, relativePath), "utf8");

describe("interaction-only bundle boundaries", () => {
  it("does not import the settings dialog until its store is open", () => {
    const host = read(
      "src/components/workspace/settings/settings-dialog-host.tsx",
    );
    expect(host).toContain("dynamic(");
    expect(host).toContain("if (!open)");
    expect(host).not.toContain(
      'import { SettingsDialog } from "./settings-dialog"',
    );
  });

  it("loads each settings page from its active section", () => {
    const dialog = read(
      "src/components/workspace/settings/settings-dialog.tsx",
    );
    expect(dialog.match(/dynamic\(/g)).toHaveLength(9);
    expect(dialog).not.toMatch(
      /import \{ \w+SettingsPage \} from "@\/components\/workspace\/settings\//,
    );
  });

  it("keeps right-panel implementations behind dynamic imports", () => {
    const chatBox = read("src/components/workspace/chats/chat-box.tsx");
    expect(chatBox).toContain('import dynamic from "next/dynamic"');
    expect(chatBox).not.toMatch(
      /import \{ (?:ArtifactFileDetail|ArtifactFileList|BrowserViewPanel|SidecarPanel)/,
    );
    expect(chatBox.match(/dynamic\(/g)?.length).toBeGreaterThanOrEqual(4);
  });

  it("keeps result-area navigation visible while an artifact is previewed", () => {
    const chatBox = read("src/components/workspace/chats/chat-box.tsx");

    expect(chatBox).toContain("{t.common.resultArea}");
    expect(chatBox).toContain("{t.common.resultArtifacts}");
    expect(chatBox).not.toContain(
      'if (renderedRightPanel === "artifacts" && selectedArtifact)',
    );
    expect(chatBox).toMatch(
      /renderedRightPanel === "artifacts"[\s\S]*?selectedArtifact \?[\s\S]*?<ArtifactFileDetail/,
    );
  });
});
