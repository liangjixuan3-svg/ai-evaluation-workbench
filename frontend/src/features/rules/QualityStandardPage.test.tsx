import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { PublishedStandardNote } from "./QualityStandardPage";

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
