import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LanguagePicker from "./LanguagePicker";
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
it("searches variants and excludes auto for target selections", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify({
        items: [
          {
            code: "zh",
            name: "Chinese",
            iso639_3: "cmn",
            aliases: ["中文"],
            direction: "auto",
            variants: ["zh-Hans", "zh-Hant"],
            is_auto: false,
          },
        ],
        total: 1,
      }),
      { status: 200 },
    ),
  );
  const onChange = vi.fn();
  const user = userEvent.setup();
  render(<LanguagePicker target value="" onChange={onChange} />);
  await user.type(screen.getByLabelText("搜索语言"), "中文");
  await user.click(
    await screen.findByRole("button", { name: "Chinese · zh-Hant" }),
  );
  expect(onChange).toHaveBeenCalledWith("zh-Hant");
  expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain(
    "include_auto=false",
  );
});
