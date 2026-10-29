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
it("saves a separate custom translation credential without retaining it", async () => {
  const user = userEvent.setup();
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
    if (path.endsWith("/credentials/translation") && init?.method === "PUT")
      return ok({ revision: 1, configured: true });
    throw new Error(path);
  });
  render(<App />);
  await user.click(await screen.findByText("自定义翻译服务凭据"));
  const input = screen.getByLabelText("自定义翻译访问令牌") as HTMLInputElement;
  await user.type(input, "custom_fake");
  await user.click(screen.getByRole("button", { name: "保存自定义令牌" }));
  await waitFor(() => expect(input.value).toBe(""));
});
it("allows an explicitly configured custom translation endpoint with its separate credential", async () => {
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
          translation: { revision: 1, configured: true },
        },
        providers: {},
      });
    if (path.endsWith("/providers/translation")) {
      saved = JSON.parse(String(init?.body));
      return ok({ ...saved, revision: 1 });
    }
    throw new Error(path);
  });
  render(<App />);
  await user.click((await screen.findAllByText("查看连接信息"))[2]);
  await user.selectOptions(
    screen.getByLabelText("翻译服务类型"),
    "openai_compatible",
  );
  const endpoint = screen.getByLabelText("翻译端点");
  await user.clear(endpoint);
  await user.type(endpoint, "https://custom.example/v1");
  await user.click(screen.getByRole("button", { name: "保存翻译设置" }));
  await waitFor(() => expect(saved?.adapter).toBe("openai_compatible"));
  expect(saved?.credential_ref).toBe("translation");
});
it("shows actual account and duration facts without claiming inference success", async () => {
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
          huggingface: { revision: 1, configured: true },
          translation: { revision: 0, configured: false },
        },
        providers: {
          transcription: {
            revision: 1,
            adapter: "nvidia_stream",
            endpoint: "https://nvidia-nemotron-diarization.hf.space",
            model: "m",
            controls: {},
            credential_ref: null,
          },
        },
      });
    if (path.endsWith("/providers/transcription/check"))
      return ok({
        state: "reachable",
        reachable: true,
        credentials_valid: null,
        inference_verified: false,
        limits: { max_duration_seconds: 120 },
        capabilities: { coverage: "English file streaming" },
      });
    throw new Error(path);
  });
  render(<App />);
  await user.click(
    await screen.findByRole("button", { name: "检查识别与角色" }),
  );
  expect(await screen.findByText(/120 秒/)).toBeTruthy();
  expect(screen.getAllByText(/实际推理未验证/).length).toBeGreaterThan(0);
});
it("discloses OmniVoice pretrained model noncommercial license separately from code", async () => {
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
        providers: {},
      });
    throw new Error(path);
  });
  render(<App />);
  const user = userEvent.setup();
  await user.click((await screen.findAllByText("查看连接信息"))[3]);
  expect(screen.getByText(/预训练模型.*CC-BY-NC/)).toBeTruthy();
  expect(screen.getByText(/上游代码.*Apache-2.0/)).toBeTruthy();
});
it("registers a workspace and logs out through the API", async () => {
  const user = userEvent.setup();
  let loggedOut = false;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (path.endsWith("/auth/me")) return ok({}, 401);
    if (path.endsWith("/auth/register"))
      return ok(
        { csrf_token: "csrf", user: { name: "New" }, workspace: { name: "W" } },
        201,
      );
    if (path.endsWith("/provider-settings"))
      return ok({
        credentials: {
          huggingface: { revision: 0, configured: false },
          translation: { revision: 0, configured: false },
        },
        providers: {},
      });
    if (path.endsWith("/auth/logout")) {
      loggedOut = init?.method === "POST";
      return new Response(null, { status: 204 });
    }
    throw new Error(path);
  });
  render(<App />);
  await user.click(await screen.findByText("还没有账号？创建账号"));
  await user.type(screen.getByLabelText("名称"), "New");
  await user.type(screen.getByLabelText("邮箱"), "new@example.com");
  await user.type(screen.getByLabelText("密码"), "password123");
  await user.click(screen.getByRole("button", { name: "创建账号" }));
  await user.click(await screen.findByRole("button", { name: "退出登录" }));
  expect(loggedOut).toBe(true);
  expect(await screen.findByRole("button", { name: "登录" })).toBeTruthy();
});
it("returns to login when an established session expires", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = String(input);
    if (path.endsWith("/auth/me"))
      return ok({
        csrf_token: "csrf",
        user: { name: "M" },
        workspace: { name: "W" },
      });
    if (path.endsWith("/provider-settings")) return ok({}, 401);
    throw new Error(path);
  });
  render(<App />);
  expect(await screen.findByRole("button", { name: "登录" })).toBeTruthy();
});
it("preserves existing controls when editing a model", async () => {
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
          synthesis: {
            revision: 1,
            adapter: "omnivoice",
            endpoint: "https://k2-fsa-omnivoice.hf.space",
            model: "old",
            controls: { ns: 48 },
            credential_ref: "huggingface",
          },
        },
      });
    if (path.endsWith("/providers/synthesis")) {
      saved = JSON.parse(String(init?.body));
      return ok({ ...saved, revision: 2 });
    }
    throw new Error(path);
  });
  render(<App />);
  await user.click((await screen.findAllByText("查看连接信息"))[3]);
  await user.click(screen.getByRole("button", { name: "保存声音克隆设置" }));
  await waitFor(() => expect(saved).toBeDefined());
  expect(saved?.controls).toEqual({ ns: 48 });
});
it("allows editing the Space ID without losing it on save", async () => {
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
    if (path.endsWith("/providers/synthesis")) {
      saved = JSON.parse(String(init?.body));
      return ok({ ...saved, revision: 1 });
    }
    throw new Error(path);
  });
  render(<App />);
  await user.click((await screen.findAllByText("查看连接信息"))[3]);
  const field = screen.getByLabelText("声音克隆 Space ID");
  await user.clear(field);
  await user.type(field, "owner/other-space");
  await user.click(screen.getByRole("button", { name: "保存声音克隆设置" }));
  await waitFor(() => expect(saved?.space_id).toBe("owner/other-space"));
});
it("allows a custom translation service with no credential when appropriate", async () => {
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
    if (path.endsWith("/providers/translation")) {
      saved = JSON.parse(String(init?.body));
      return ok({ ...saved, revision: 1 });
    }
    throw new Error(path);
  });
  render(<App />);
  await user.click((await screen.findAllByText("查看连接信息"))[2]);
  await user.selectOptions(
    screen.getByLabelText("翻译服务类型"),
    "openai_compatible",
  );
  await user.selectOptions(screen.getByLabelText("翻译服务凭据"), "none");
  await user.click(screen.getByRole("button", { name: "保存翻译设置" }));
  await waitFor(() => expect(saved?.credential_ref).toBe(null));
});
it("associates login errors with credential fields", async () => {
  const user = userEvent.setup();
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
    String(input).endsWith("/auth/me") ? ok({}, 401) : ok({}, 401),
  );
  render(<App />);
  const email = await screen.findByLabelText("邮箱");
  await user.type(email, "a@example.com");
  await user.type(screen.getByLabelText("密码"), "password123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  const alert = await screen.findByRole("alert");
  expect(email.getAttribute("aria-invalid")).toBe("true");
  expect(email.getAttribute("aria-describedby")).toBe(alert.id);
  expect(screen.getByLabelText("密码").getAttribute("aria-describedby")).toBe(
    alert.id,
  );
});
it("associates credential validation errors with the token input", async () => {
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
        providers: {},
      });
    return ok({}, 422);
  });
  render(<App />);
  const token = await screen.findByLabelText("Hugging Face 访问令牌");
  await user.type(token, "fake");
  await user.click(screen.getByRole("button", { name: "保存令牌" }));
  const alert = await screen.findByRole("alert");
  expect(token.getAttribute("aria-invalid")).toBe("true");
  expect(token.getAttribute("aria-describedby")).toBe(alert.id);
});
it("marks fixed provider model and NVIDIA endpoint as read only", async () => {
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
        providers: {},
      });
    throw new Error(path);
  });
  const user = userEvent.setup();
  render(<App />);
  await user.click((await screen.findAllByText("查看连接信息"))[1]);
  expect(
    (screen.getByLabelText("识别与角色端点") as HTMLInputElement).readOnly,
  ).toBe(true);
  expect(
    (screen.getByLabelText("识别与角色模型") as HTMLInputElement).readOnly,
  ).toBe(true);
});
it("associates stale service response without marking valid fields invalid", async () => {
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
        providers: {},
      });
    return ok({}, 409);
  });
  render(<App />);
  await user.click((await screen.findAllByText("查看连接信息"))[2]);
  const model = screen.getByLabelText("翻译模型");
  await user.type(model, "draft/model");
  await user.click(screen.getByRole("button", { name: "保存翻译设置" }));
  const alert = await screen.findByRole("alert");
  expect(model.getAttribute("aria-describedby")).toBe(alert.id);
  expect(model.getAttribute("aria-invalid")).not.toBe("true");
  expect((model as HTMLInputElement).value).toBe("draft/model");
});
