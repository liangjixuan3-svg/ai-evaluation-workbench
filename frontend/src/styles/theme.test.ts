import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const theme = readFileSync(new URL("./theme.css", import.meta.url), "utf8");

describe("全站可读性规范", () => {
  it("定义正文、辅助信息和控件的最低字号", () => {
    expect(theme).toContain("--font-body: 13px");
    expect(theme).toContain("--font-support: 11px");
    expect(theme).toContain("--font-control: 13px");
  });

  it("移动端导航标签不小于 10px", () => {
    expect(theme).toMatch(/\.sidebar nav a \{[^}]*font-size: 10px !important/);
    expect(theme).toMatch(/\.hero p \{ font-size: 13px; \}/);
    expect(theme).toMatch(/\.score-stamp span, \.score-stamp small \{ font-size: 11px; \}/);
  });
});
