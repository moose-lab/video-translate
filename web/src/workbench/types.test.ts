import {expect, it} from "vitest";
import {stageName} from "./types";
it("identifies context and reference jobs by their actual stages", () => {
  expect(stageName("translation_context")).toBe("翻译上下文");
  expect(stageName("reference")).toBe("参考音提取");
});
