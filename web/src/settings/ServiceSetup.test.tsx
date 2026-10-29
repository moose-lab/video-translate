import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ServiceSetup from "./ServiceSetup";
const ok = (data: unknown) =>
  new Response(JSON.stringify(data), {
    headers: { "Content-Type": "application/json" },
  });
it("preserves custom credential revision when another pending save resolves", async () => {
  const user = userEvent.setup();
  let finishService: (r: Response) => void = () => {};
  const servicePromise = new Promise<Response>((resolve) => {
    finishService = resolve;
  });
  const revisions: number[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (path.endsWith("/provider-settings"))
      return ok({
        credentials: {
          huggingface: { revision: 0, configured: false },
          translation: { revision: 0, configured: false },
        },
        providers: {},
      });
    if (path.endsWith("/providers/separation")) return servicePromise;
    if (path.endsWith("/credentials/translation")) {
      const body = JSON.parse(String(init?.body));
      revisions.push(body.revision);
      return ok({ revision: revisions.length, configured: true });
    }
    throw new Error(path);
  });
  render(<ServiceSetup csrf="fake" logout={() => {}} />);
  await screen.findByLabelText("Hugging Face 访问令牌");
  await user.click(screen.getByText("自定义翻译服务凭据"));
  await user.type(screen.getByLabelText("自定义翻译访问令牌"), "fake-first");
  await user.click(screen.getAllByRole("button", { name: "保存默认设置" })[0]);
  await user.click(screen.getByRole("button", { name: "保存自定义令牌" }));
  await waitFor(() => expect(revisions).toEqual([0]));
  await waitFor(() =>
    expect(
      (screen.getByLabelText("自定义翻译访问令牌") as HTMLInputElement).value,
    ).toBe(""),
  );
  finishService(ok({ revision: 1, adapter: "demucs" }));
  await screen.findByText("背景分离设置已保存。");
  await user.type(screen.getByLabelText("自定义翻译访问令牌"), "fake-second");
  await user.click(screen.getByRole("button", { name: "保存自定义令牌" }));
  await waitFor(() => expect(revisions.length).toBe(2));
  expect(revisions).toEqual([0, 1]);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
it("invalidates the displayed account verification after clearing HF credentials", async () => {
  const user = userEvent.setup();
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = String(input);
    if (path.endsWith("/provider-settings"))
      return ok({
        credentials: {
          huggingface: { revision: 1, configured: true },
          translation: { revision: 0, configured: false },
        },
        providers: {
          translation: {
            revision: 1,
            adapter: "hf_router",
            credential_ref: "huggingface",
            check_state: {
              state: "reachable",
              credentials_valid: true,
              credential_revision: 1,
              inference_verified: false,
            },
          },
        },
      });
    if (path.endsWith("/credentials/huggingface"))
      return ok({ revision: 2, configured: false });
    throw new Error(path);
  });
  render(<ServiceSetup csrf="fake" logout={() => {}} />);
  await screen.findByText("账号验证通过；实际推理权限未验证。");
  await user.click(screen.getByRole("button", { name: "清除令牌" }));
  await screen.findByText("令牌已清除。");
  expect(screen.queryByText("账号验证通过；实际推理权限未验证。")).toBeNull();
});

it("disables credential input while its save is pending", async () => {
  const user = userEvent.setup();
  let finish: (r: Response) => void = () => {};
  const pending = new Promise<Response>((resolve) => {
    finish = resolve;
  });
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
    String(input).endsWith("/provider-settings")
      ? ok({
          credentials: {
            huggingface: { revision: 0, configured: false },
            translation: { revision: 0, configured: false },
          },
          providers: {},
        })
      : pending,
  );
  render(<ServiceSetup csrf="fake" logout={() => {}} />);
  const field = (await screen.findByLabelText(
    "Hugging Face 访问令牌",
  )) as HTMLInputElement;
  await user.type(field, "hf_fake");
  await user.click(screen.getByRole("button", { name: "保存令牌" }));
  expect(field.disabled).toBe(true);
  finish(ok({ revision: 1, configured: true }));
  await waitFor(() => expect(field.disabled).toBe(false));
});
it("late provider check cannot restore an old credential verification", async () => {
  const user = userEvent.setup();
  let finish: (r: Response) => void = () => {};
  const checking = new Promise<Response>((resolve) => {
    finish = resolve;
  });
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = String(input);
    if (path.endsWith("/provider-settings"))
      return ok({
        credentials: {
          huggingface: { revision: 0, configured: false },
          translation: { revision: 0, configured: false },
        },
        providers: {
          translation: {
            revision: 1,
            adapter: "openai_compatible",
            credential_ref: "translation",
          },
        },
      });
    if (path.endsWith("/providers/translation/check")) return checking;
    if (path.endsWith("/credentials/translation"))
      return ok({ revision: 1, configured: true });
    throw new Error(path);
  });
  render(<ServiceSetup csrf="fake" logout={() => {}} />);
  await user.click(await screen.findByRole("button", { name: "检查翻译" }));
  await user.click(screen.getByText("自定义翻译服务凭据"));
  await user.type(screen.getByLabelText("自定义翻译访问令牌"), "fake-token");
  await user.click(screen.getByRole("button", { name: "保存自定义令牌" }));
  await waitFor(() =>
    expect(
      (screen.getByLabelText("自定义翻译访问令牌") as HTMLInputElement).value,
    ).toBe(""),
  );
  finish(
    ok({
      state: "reachable",
      reachable: true,
      credentials_valid: true,
      credential_revision: 0,
      inference_verified: false,
    }),
  );
  await screen.findByText("服务可连接");
  expect(screen.queryByText("账号验证通过；实际推理权限未验证。")).toBeNull();
});
