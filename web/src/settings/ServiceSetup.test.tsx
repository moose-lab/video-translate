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

it("offers the explicit public four-stem profile for new configuration", async () => {
  const user = userEvent.setup();
  const bodies: Record<string, unknown>[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (String(input).endsWith("/provider-settings")) return ok({
      credentials: { huggingface: { revision: 0, configured: false }, translation: { revision: 0, configured: false } }, providers: {},
    });
    const body = JSON.parse(String(init?.body));
    bodies.push(body);
    return ok({ ...body, revision: 1 });
  });
  render(<ServiceSetup csrf="fake" logout={() => {}} />);
  await screen.findByLabelText("Hugging Face 访问令牌");
  await user.click(screen.getAllByText("查看连接信息")[0]);
  const profile = screen.getByLabelText("背景分离服务类型") as HTMLSelectElement;
  expect(profile.value).toBe("demucs_multistem");
  expect(screen.getAllByRole("button", { name: "保存默认设置" })).toHaveLength(5);
  await user.click(screen.getByRole("button", { name: "保存背景分离设置", hidden: true }));
  await waitFor(() => expect(bodies).toHaveLength(1));
  expect(bodies[0]).toMatchObject({ adapter: "demucs_multistem", model: "htdemucs", space_id: "teamup-tech/Demucs", endpoint: "https://teamup-tech-demucs.hf.space", credential_ref: null });
  expect(screen.getByText(/鼓、贝斯与其他/)).toBeTruthy();
  expect(screen.getByText(/更新 Hugging Face 令牌不能解决公开文件权限/)).toBeTruthy();
});

it("keeps saved two-stem settings until the owner explicitly selects four stems", async () => {
  const user = userEvent.setup();
  const legacy = { revision: 7, adapter: "demucs", model: "htdemucs_ft", space_id: "kajise/Demucs_v4-FT_2s", endpoint: "https://kajise-demucs-v4-ft-2s.hf.space", credential_ref: null };
  const bodies: Record<string, unknown>[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (String(input).endsWith("/provider-settings")) return ok({ credentials: { huggingface: { revision: 0, configured: false }, translation: { revision: 0, configured: false } }, providers: { separation: legacy } });
    const body = JSON.parse(String(init?.body));
    bodies.push(body);
    return ok({ ...body, revision: 8 });
  });
  render(<ServiceSetup csrf="fake" logout={() => {}} />);
  await screen.findByLabelText("Hugging Face 访问令牌");
  await user.click(screen.getAllByText("查看连接信息")[0]);
  const profile = screen.getByLabelText("背景分离服务类型") as HTMLSelectElement;
  expect(profile.value).toBe("demucs");
  expect((screen.getByLabelText("背景分离模型") as HTMLInputElement).value).toBe("htdemucs_ft");
  await user.click(screen.getAllByRole("button", { name: "保存默认设置" })[0]);
  await waitFor(() => expect(bodies).toHaveLength(1));
  expect(bodies[0]).toMatchObject(legacy);
  await user.selectOptions(profile, "demucs_multistem");
  expect((screen.getByLabelText("背景分离模型") as HTMLInputElement).value).toBe("htdemucs");
  expect((screen.getByLabelText("背景分离 Space ID") as HTMLInputElement).value).toBe("teamup-tech/Demucs");
  expect(screen.getAllByRole("link", { name: "查看服务来源", hidden: true })[0].getAttribute("href")).toContain("teamup-tech/Demucs");
  await user.click(screen.getByRole("button", { name: "保存背景分离设置" }));
  await waitFor(() => expect(bodies).toHaveLength(2));
  expect(bodies[1]).toMatchObject({
    revision: 8, adapter: "demucs_multistem", model: "htdemucs",
    space_id: "teamup-tech/Demucs", endpoint: "https://teamup-tech-demucs.hf.space",
  });
});

for (const adapter of ["demucs", "demucs_multistem"] as const) {
  for (const endpointState of ["null", "omitted"] as const) {
    for (const button of ["default", "expanded"] as const) {
      it(`round-trips ${adapter} ${endpointState} endpoint with ${button} save`, async () => {
        const user = userEvent.setup();
        const loaded = {
          revision: 7,
          adapter,
          model: adapter === "demucs" ? "htdemucs_ft" : "htdemucs",
          space_id: adapter === "demucs" ? "kajise/Demucs_v4-FT_2s" : "teamup-tech/Demucs",
          credential_ref: null,
          ...(endpointState === "null" ? { endpoint: null } : {}),
        };
        const bodies: Record<string, unknown>[] = [];
        vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
          if (String(input).endsWith("/provider-settings")) return ok({
            credentials: {
              huggingface: { revision: 0, configured: false },
              translation: { revision: 0, configured: false },
            },
            providers: { separation: loaded },
          });
          const body = JSON.parse(String(init?.body));
          bodies.push(body);
          return ok({ ...body, revision: 8 });
        });
        render(<ServiceSetup csrf="fake" logout={() => {}} />);
        await screen.findByLabelText("Hugging Face 访问令牌");
        await user.click(screen.getAllByText("查看连接信息")[0]);
        expect((screen.getByLabelText("背景分离模型") as HTMLInputElement).value).toBe(loaded.model);
        expect((screen.getByLabelText("背景分离 Space ID") as HTMLInputElement).value).toBe(loaded.space_id);
        await user.click(button === "default"
          ? screen.getAllByRole("button", { name: "保存默认设置" })[0]
          : screen.getByRole("button", { name: "保存背景分离设置" }));
        await waitFor(() => expect(bodies).toHaveLength(1));
        expect(bodies[0]).toMatchObject(loaded);
        if (endpointState === "null") {
          expect(bodies[0]).toHaveProperty("endpoint", null);
        } else {
          expect(bodies[0]).not.toHaveProperty("endpoint");
        }
        expect(bodies[0].endpoint).not.toBe("");
        // A saved Space-resolved endpoint is blank, never the other profile's host.
        expect((screen.getByLabelText("背景分离端点") as HTMLInputElement).value).toBe("");
      });
    }
  }
}
