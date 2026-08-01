import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { QualityStandardSummary } from "../../app/qualityStandardApi";
import { PublishedStandardNote, visibleQualityStandards } from "./QualityStandardPage";

describe("PublishedStandardNote", () => {
  it("links to the published version detail", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <PublishedStandardNote versionId="version-1" versionNumber={1} />
      </MemoryRouter>,
    );

    expect(html).toContain('href="/rules/versions/version-1"');
    expect(html).toContain("查看 V1 完整规则");
  });
});

describe("visibleQualityStandards", () => {
  it("hides published legacy records without a valid published version", () => {
    const item = (overrides: Partial<QualityStandardSummary>): QualityStandardSummary => ({
      id: "standard-1",
      name: "客服质量标准",
      status: "published",
      latest_version: 1,
      published_version_id: "version-1",
      published_rules: null,
      updated_at: "2026-08-01T00:00:00Z",
      ...overrides,
    });

    const visible = visibleQualityStandards([
      item({ id: "legacy", name: "trigger-test-legacy", published_version_id: null }),
      item({ id: "valid" }),
      item({ id: "draft", status: "draft", published_version_id: null }),
    ]);

    expect(visible.map((standard) => standard.id)).toEqual(["valid", "draft"]);
  });
});
