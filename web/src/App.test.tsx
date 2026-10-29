import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
const ok = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
it("logs in and saves a credential without keeping it in the form or browser storage", async () => {
  const user = userEvent.setup();
  const fetchMock = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      const path = String(input);
      if (path.endsWith("/auth/me")) return ok({}, 401);
      if (path.endsWith("/auth/login"))
        return ok({
          csrf_token: "csrf",
          user: { name: "M" },
          workspace: { name: "工作室" },
        });
      if (path.endsWith("/provider-settings"))
        return ok({
          credentials: {
            huggingface: { revision: 0, configured: false },
            translation: { revision: 0, configured: false },
          },
          providers: {},
        });
      if (path.endsWith("/credentials/huggingface") && init?.method === "PUT")
        return ok({ revision: 1, configured: true });
      throw new Error(path);
    });
  render(<App />);
  await user.type(await screen.findByLabelText("邮箱"), "user@example.com");
  await user.type(screen.getByLabelText("密码"), "password123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  const secret = (await screen.findByLabelText(
    "Hugging Face 访问令牌",
  )) as HTMLInputElement;
  await user.type(secret, "hf_test_value");
  await user.click(screen.getByRole("button", { name: "保存令牌" }));
  await waitFor(() => expect(secret.value).toBe(""));
  expect(localStorage.length).toBe(0);
  expect(sessionStorage.length).toBe(0);
  expect(
    fetchMock.mock.calls.some(([path]) =>
      String(path).endsWith("/credentials/huggingface"),
    ),
  ).toBe(true);
});
it("saves a preset with only provider configuration fields", async () => {
  const user = userEvent.setup();
  let saved: Record<string, unknown> | undefined;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (path.endsWith("/auth/me"))
      return ok({
        csrf_token: "csrf",
        user: { name: "M" },
        workspace: { name: "W" },
      });
    if (path.endsWith("/provider-settings"))
      return ok({
        credentials: {
          huggingface: { revision: 0, configured: false },
          translation: { revision: 0, configured: false },
        },
        providers: {},
      });
    if (path.endsWith("/providers/separation")) {
      saved = JSON.parse(String(init?.body));
      return ok({ ...saved, revision: 1 });
    }
    throw new Error(path);
  });
  render(<App />);
  await user.click(
    (await screen.findAllByRole("button", { name: "保存默认设置" }))[0],
  );
  await waitFor(() => expect(saved).toBeDefined());
  expect(saved).not.toHaveProperty("name");
  expect(saved).not.toHaveProperty("desc");
  expect(saved).not.toHaveProperty("slot");
});
it("edits and saves the configured model in advanced settings", async () => {
  const user = userEvent.setup();
  let saved: Record<string, unknown> | undefined;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (path.endsWith("/auth/me"))
      return ok({
        csrf_token: "csrf",
        user: { name: "M" },
        workspace: { name: "W" },
      });
    if (path.endsWith("/provider-settings"))
      return ok({
        credentials: {
          huggingface: { revision: 0, configured: false },
          translation: { revision: 0, configured: false },
        },
        providers: {
          translation: {
            revision: 1,
            adapter: "hf_router",
            endpoint: "https://router.huggingface.co/v1",
            model: "old",
            controls: {},
            credential_ref: "huggingface",
          },
        },
      });
    if (path.endsWith("/providers/translation")) {
      saved = JSON.parse(String(init?.body));
      return ok({ ...saved, revision: 2 });
    }
    throw new Error(path);
  });
  render(<App />);
  await user.click((await screen.findAllByText("查看连接信息"))[2]);
  const model = screen.getByLabelText("翻译模型");
  await user.clear(model);
  await user.type(model, "new-model");
  await user.click(screen.getByRole("button", { name: "保存翻译设置" }));
  await waitFor(() => expect(saved?.model).toBe("new-model"));
});
it("shows the actual check result and explicitly marks inference unverified", async () => {
  const user = userEvent.setup();
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = String(input);
    if (path.endsWith("/auth/me"))
      return ok({
        csrf_token: "csrf",
        user: { name: "M" },
        workspace: { name: "W" },
      });
    if (path.endsWith("/provider-settings"))
      return ok({
        credentials: {
          huggingface: { revision: 0, configured: false },
          translation: { revision: 0, configured: false },
        },
        providers: {
          translation: {
            revision: 1,
            adapter: "hf_router",
            endpoint: "https://router.huggingface.co/v1",
            model: "test",
            controls: {},
            credential_ref: "huggingface",
          },
        },
      });
    if (path.endsWith("/providers/translation/check"))
      return ok({
        state: "credential_required",
        reachable: null,
        credentials_valid: null,
        inference_verified: false,
      });
    throw new Error(path);
  });
  render(<App />);
  await user.click(await screen.findByRole("button", { name: "检查翻译" }));
  expect(await screen.findByText("需要配置令牌")).toBeTruthy();
  expect(screen.getAllByText(/实际推理未验证/).length).toBeGreaterThan(0);
});
