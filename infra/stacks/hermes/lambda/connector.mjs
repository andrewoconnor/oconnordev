const OWNER = "andrewoconnor";
const MAX_FILES = 25;
const MAX_FILE_BYTES = 128 * 1024;
const MAX_TOTAL_BYTES = 512 * 1024;
const MAX_API_BYTES = 600 * 1024;
const GITHUB_API = "https://api.github.com";
const API_VERSION = "2022-11-28";
const TOOL_FIELDS = {
  repository_info: ["repository"],
  read_files: ["repository", "paths", "ref"],
  submit_change: ["repository", "request_id", "expected_base_sha", "title", "body", "files"],
  revise_change: ["repository", "pull_number", "request_id", "expected_head_sha", "files"],
  change_status: ["repository", "pull_number"],
};
const TEXT_EXTENSIONS = new Set([
  "cjs", "cfg", "css", "csv", "go", "hcl", "html", "ini", "java", "js", "json", "jsx", "kt", "lock", "md", "mdx", "mjs", "py", "rs", "scss", "sh", "sql", "svelte", "toml", "ts", "tsx", "tf", "txt", "vue", "xml", "yaml", "yml",
]);
const TEXT_BASENAMES = new Set(["Dockerfile", "LICENSE", "Makefile", "NOTICE"]);

export class SafeError extends Error {
  constructor(category, status = 400) {
    super(category);
    this.name = "SafeError";
    this.category = category;
    this.status = status;
  }
}

function fail(category, status) {
  throw new SafeError(category, status);
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value) && (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null);
}

function exactKeys(value, allowed, required = allowed) {
  if (!isRecord(value)) fail("invalid_arguments");
  const keys = Object.keys(value);
  if (keys.some((key) => !allowed.includes(key)) || required.some((key) => !Object.hasOwn(value, key))) fail("invalid_arguments");
}

function boundedString(value, max, category = "invalid_arguments") {
  if (typeof value !== "string" || value.length === 0 || value.length > max || value.includes("\0")) fail(category);
  return value;
}

function validateRepoName(value, allowedRepos) {
  boundedString(value, 100);
  if (!/^[A-Za-z0-9_.-]+$/.test(value) || value.startsWith(".") || value.endsWith(".git")) fail("invalid_repository");
  if (!allowedRepos.has(value.toLowerCase())) fail("repository_not_allowed", 403);
  return value;
}

function validatePath(path) {
  boundedString(path, 512);
  if (path.startsWith("/") || path.includes("\\") || path.split("/").some((part) => part === "" || part === "." || part === "..") || path.toLowerCase().includes("%2e")) fail("invalid_path");
  if (path.split("/").some((part) => part.toLowerCase() === ".git")) fail("unsupported_path");
  const basename = path.split("/").at(-1);
  const extension = basename.includes(".") ? basename.split(".").at(-1).toLowerCase() : "";
  if (!TEXT_EXTENSIONS.has(extension) && !TEXT_BASENAMES.has(basename)) fail("unsupported_file_type");
  if (/\.(?:env|pem|key|p12|pfx|crt|cer|tfstate|secret|secrets)(?:\.|$)/i.test(basename) || basename === ".env") fail("unsupported_path");
  return path;
}

function validateRef(value) {
  boundedString(value, 255);
  if (!/^[A-Za-z0-9._/-]+$/.test(value) || value.startsWith("/") || value.endsWith("/") || value.includes("..") || value.includes("//") || value.endsWith(".lock")) fail("invalid_ref");
  return value;
}

function validateRequestId(value) {
  boundedString(value, 64);
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(value) || value.endsWith(".lock")) fail("invalid_request_id");
  return value;
}

function validateSha(value) {
  boundedString(value, 40);
  if (!/^[a-f0-9]{40}$/i.test(value)) fail("invalid_sha");
  return value.toLowerCase();
}

function validatePullNumber(value) {
  if (!Number.isSafeInteger(value) || value < 1 || value > 2147483647) fail("invalid_pull_number");
  return value;
}

function validateFiles(files) {
  if (!Array.isArray(files) || files.length < 1 || files.length > MAX_FILES) fail("invalid_file_count");
  const seen = new Set();
  let total = 0;
  const result = files.map((file) => {
    exactKeys(file, ["path", "content"]);
    const path = validatePath(file.path);
    if (seen.has(path)) fail("duplicate_path");
    seen.add(path);
    if (typeof file.content !== "string" || file.content.includes("\0") || Buffer.from(file.content, "utf8").toString("utf8") !== file.content) fail("binary_content_not_supported");
    const bytes = Buffer.byteLength(file.content, "utf8");
    if (bytes > MAX_FILE_BYTES) fail("file_too_large", 413);
    total += bytes;
    if (total > MAX_TOTAL_BYTES) fail("payload_too_large", 413);
    return { path, content: file.content };
  });
  return result;
}

function validateReadPaths(paths) {
  if (!Array.isArray(paths) || paths.length < 1 || paths.length > MAX_FILES) fail("invalid_file_count");
  const seen = new Set();
  return paths.map((path) => {
    const safe = validatePath(path);
    if (seen.has(safe)) fail("duplicate_path");
    seen.add(safe);
    return safe;
  });
}

function encodePath(path) {
  return path.split("/").map(encodeURIComponent).join("/");
}

function encodeRef(ref) {
  return ref.split("/").map(encodeURIComponent).join("/");
}

function jsonBody(value) {
  return JSON.stringify(value);
}

async function boundedResponseBody(response) {
  const length = Number(response.headers?.get?.("content-length") || 0);
  if (length > MAX_API_BYTES) fail("github_response_too_large", 502);
  if (!response.body?.getReader) {
    const text = await response.text();
    if (Buffer.byteLength(text, "utf8") > MAX_API_BYTES) fail("github_response_too_large", 502);
    return text;
  }
  const reader = response.body.getReader();
  const chunks = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > MAX_API_BYTES) {
      await reader.cancel();
      fail("github_response_too_large", 502);
    }
    chunks.push(Buffer.from(value));
  }
  return Buffer.concat(chunks).toString("utf8");
}

export function createGitHubApi({ appId, installationId, getPrivateKey, fetchImpl = fetch, now = () => Date.now() }) {
  async function appJwt() {
    let privateKey;
    try {
      privateKey = await getPrivateKey();
    } catch {
      fail("secrets_manager_failure", 502);
    }
    if (typeof privateKey !== "string" || !privateKey.includes("-----BEGIN")) fail("secrets_manager_failure", 502);
    const issuedAt = Math.floor(now() / 1000) - 30;
    const header = Buffer.from(JSON.stringify({ alg: "RS256", typ: "JWT" })).toString("base64url");
    const payload = Buffer.from(JSON.stringify({ iat: issuedAt, exp: issuedAt + 540, iss: appId })).toString("base64url");
    const unsigned = `${header}.${payload}`;
    const signature = (await import("node:crypto")).sign("RSA-SHA256", Buffer.from(unsigned), privateKey).toString("base64url");
    return `${unsigned}.${signature}`;
  }

  async function request(path, { method = "GET", token, jwt, body } = {}) {
    if (!path.startsWith("/") || path.startsWith("//") || path.includes("..")) fail("github_request_rejected", 500);
    const url = new URL(path, GITHUB_API);
    if (url.origin !== GITHUB_API) fail("github_request_rejected", 500);
    const headers = {
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": API_VERSION,
      "User-Agent": "hermes-github-change-proposal",
    };
    if (token) headers.Authorization = `Bearer ${token}`;
    else if (jwt) headers.Authorization = `Bearer ${jwt}`;
    else fail("github_authentication_failure", 502);
    if (body !== undefined) headers["Content-Type"] = "application/json";
    let response;
    try {
      response = await fetchImpl(url, {
        method,
        headers,
        body: body === undefined ? undefined : jsonBody(body),
        redirect: "error",
        signal: AbortSignal.timeout(8_000),
      });
    } catch {
      fail("github_transport_failure", 502);
    }
    if (response.status === 401) fail("github_authentication_failure", 502);
    if (response.status === 403) fail("github_permission_denied", 403);
    if (response.status === 404) fail("github_resource_not_found", 404);
    if (response.status === 409 || response.status === 422) fail("github_conflict", 409);
    if (!response.ok) fail("github_api_failure", 502);
    if (response.status === 204) return null;
    const text = await boundedResponseBody(response);
    try {
      return JSON.parse(text);
    } catch {
      fail("github_invalid_response", 502);
    }
  }

  async function getInstallationToken(repository) {
    const jwt = await appJwt();
    const response = await request(`/app/installations/${encodeURIComponent(installationId)}/access_tokens`, {
      method: "POST",
      jwt,
      body: {
        repositories: [repository],
        permissions: { contents: "write", pull_requests: "write", statuses: "read" },
      },
    });
    if (!isRecord(response) || typeof response.token !== "string" || response.token.length < 10) fail("github_authentication_failure", 502);
    return response.token;
  }

  async function getAppBotLogin() {
    const app = await request("/app", { jwt: await appJwt() });
    if (!isRecord(app) || typeof app.slug !== "string" || !/^[a-z0-9-]+$/.test(app.slug)) fail("github_authentication_failure", 502);
    return `${app.slug}[bot]`;
  }

  return {
    request,
    getInstallationToken,
    getAppBotLogin,
  };
}

function createToolClient(api, token, owner, repo) {
  const base = `/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`;
  return {
    request: (path, options = {}) => api.request(`${base}${path}`, { ...options, token }),
  };
}

async function getRepository(api, token, owner, repo) {
  const gh = createToolClient(api, token, owner, repo);
  const metadata = await gh.request("");
  if (!isRecord(metadata) || metadata.owner?.type !== "User" || metadata.owner?.login?.toLowerCase() !== owner.toLowerCase() || metadata.full_name?.toLowerCase() !== `${owner}/${repo}`.toLowerCase() || typeof metadata.default_branch !== "string") fail("repository_identity_mismatch", 403);
  return metadata;
}

async function getRef(gh, branch) {
  const ref = await gh.request(`/git/ref/heads/${encodeRef(branch)}`);
  if (!isRecord(ref) || !isRecord(ref.object) || typeof ref.object.sha !== "string") fail("github_invalid_response", 502);
  return ref.object.sha.toLowerCase();
}

async function getPull(gh, pullNumber) {
  const pull = await gh.request(`/pulls/${pullNumber}`);
  if (!isRecord(pull)) fail("github_invalid_response", 502);
  return pull;
}

function validateManagedPull(pull, owner, repo, botLogin, defaultBranch) {
  if (pull.state !== "open" || pull.draft !== true || pull.user?.login !== botLogin || pull.base?.ref !== defaultBranch || pull.head?.repo?.full_name?.toLowerCase() !== `${owner}/${repo}`.toLowerCase() || typeof pull.head?.ref !== "string" || !pull.head.ref.startsWith("hermes/") || !/^[a-f0-9]{40}$/i.test(pull.head?.sha || "")) fail("pull_request_not_managed", 403);
}

async function findPullByHead(gh, owner, branch, defaultBranch) {
  const query = new URLSearchParams({ state: "open", head: `${owner}:${branch}`, base: defaultBranch });
  const pulls = await gh.request(`/pulls?${query.toString()}`);
  if (!Array.isArray(pulls)) fail("github_invalid_response", 502);
  if (pulls.length > 1) fail("github_conflict", 409);
  return pulls[0] || null;
}

async function getCommit(gh, sha) {
  const commit = await gh.request(`/git/commits/${encodeURIComponent(sha)}`);
  if (!isRecord(commit) || !isRecord(commit.tree) || typeof commit.tree.sha !== "string") fail("github_invalid_response", 502);
  return commit;
}

async function getFileAtRef(gh, path, ref) {
  const query = new URLSearchParams({ ref });
  const file = await gh.request(`/contents/${encodePath(path)}?${query.toString()}`);
  if (!isRecord(file) || file.type !== "file" || typeof file.content !== "string" || file.encoding !== "base64" || !Number.isSafeInteger(file.size) || file.size < 0 || file.size > MAX_FILE_BYTES) fail("unsupported_file_type", 413);
  const bytes = Buffer.from(file.content.replace(/\s+/g, ""), "base64");
  if (bytes.length !== file.size || bytes.length > MAX_FILE_BYTES) fail("github_invalid_response", 502);
  const content = bytes.toString("utf8");
  if (Buffer.from(content, "utf8").compare(bytes) !== 0 || content.includes("\0")) fail("binary_content_not_supported", 415);
  return content;
}

async function assertPayloadAtBranch(gh, files, branch) {
  for (const file of files) {
    const actual = await getFileAtRef(gh, file.path, branch);
    if (actual !== file.content) return false;
  }
  return true;
}

async function createFeatureCommit(gh, files, parentSha, message) {
  const parent = await getCommit(gh, parentSha);
  const tree = await gh.request("/git/trees", {
    method: "POST",
    body: {
      base_tree: parent.tree.sha,
      tree: files.map(({ path, content }) => ({ path, mode: "100644", type: "blob", content })),
    },
  });
  if (!isRecord(tree) || typeof tree.sha !== "string") fail("github_invalid_response", 502);
  const commit = await gh.request("/git/commits", {
    method: "POST",
    body: { message, tree: tree.sha, parents: [parentSha] },
  });
  if (!isRecord(commit) || typeof commit.sha !== "string") fail("github_invalid_response", 502);
  return commit.sha.toLowerCase();
}

async function optionalRef(gh, branch) {
  try {
    return await getRef(gh, branch);
  } catch (error) {
    if (error instanceof SafeError && error.category === "github_resource_not_found") return null;
    throw error;
  }
}

async function ensureRef(gh, branch, sha, expectedExistingSha) {
  try {
    await gh.request("/git/refs", { method: "POST", body: { ref: `refs/heads/${branch}`, sha } });
  } catch (error) {
    if (!(error instanceof SafeError) || error.category !== "github_conflict") throw error;
    const current = await optionalRef(gh, branch);
    if (current !== sha && current !== expectedExistingSha) fail("github_conflict", 409);
  }
}

async function updateRef(gh, branch, sha) {
  try {
    await gh.request(`/git/refs/heads/${encodeRef(branch)}`, { method: "PATCH", body: { sha, force: false } });
  } catch (error) {
    if (!(error instanceof SafeError) || error.category !== "github_conflict") throw error;
    const current = await optionalRef(gh, branch);
    if (current !== sha) fail("stale_head_sha", 409);
  }
  if (await getRef(gh, branch) !== sha) fail("stale_head_sha", 409);
}

function publicPull(pull) {
  return {
    number: pull.number,
    title: pull.title,
    state: pull.state,
    draft: pull.draft,
    url: pull.html_url,
    branch: pull.head.ref,
    head_sha: pull.head.sha,
    base_branch: pull.base.ref,
  };
}

export function createConnector({ config, getPrivateKey, fetchImpl, api: injectedApi, log = (entry) => console.log(JSON.stringify(entry)), now = () => Date.now() }) {
  const owner = config.owner || OWNER;
  if (owner !== OWNER) throw new Error("invalid trusted owner configuration");
  const appId = String(config.appId || "");
  const installationId = String(config.installationId || "");
  if ((appId !== "" && !/^\d+$/.test(appId)) || (installationId !== "" && !/^\d+$/.test(installationId))) throw new Error("invalid application configuration");
  const allowedRepos = new Set((config.allowedRepos || []).map((name) => String(name).toLowerCase()));
  const api = injectedApi || createGitHubApi({ appId, installationId, getPrivateKey, fetchImpl, now });

  async function tokenFor(repo) {
    return api.getInstallationToken(repo);
  }

  async function invoke(tool, rawArgs) {
    const fields = TOOL_FIELDS[tool];
    if (!fields) fail("unknown_tool", 404);
    const required = fields.filter((field) => !(tool === "read_files" && field === "ref"));
    exactKeys(rawArgs, fields, required);
    const repo = validateRepoName(rawArgs.repository, allowedRepos);
    const requestId = rawArgs.request_id === undefined ? null : validateRequestId(rawArgs.request_id);
    const input = {};
    if (tool === "read_files") {
      input.paths = validateReadPaths(rawArgs.paths);
      input.ref = rawArgs.ref === undefined ? null : validateRef(rawArgs.ref);
    } else if (tool === "submit_change") {
      input.expectedBaseSha = validateSha(rawArgs.expected_base_sha);
      input.title = boundedString(rawArgs.title, 256);
      if (typeof rawArgs.body !== "string" || rawArgs.body.length > 5000 || rawArgs.body.includes("\0")) fail("invalid_arguments");
      input.body = rawArgs.body;
      input.files = validateFiles(rawArgs.files);
    } else if (tool === "revise_change") {
      input.pullNumber = validatePullNumber(rawArgs.pull_number);
      input.expectedHeadSha = validateSha(rawArgs.expected_head_sha);
      input.files = validateFiles(rawArgs.files);
    } else if (tool === "change_status") {
      input.pullNumber = validatePullNumber(rawArgs.pull_number);
    }
    const started = now();
    let status = "error";
    let category = "internal_error";
    try {
      if (!appId || !installationId) fail("github_app_not_configured", 503);
      const token = await tokenFor(repo);
      const metadata = await getRepository(api, token, owner, repo);
      const gh = createToolClient(api, token, owner, repo);
      const defaultBranch = metadata.default_branch;

      let result;
      if (tool === "repository_info") {
        const sha = await getRef(gh, defaultBranch);
        result = { repository: metadata.full_name, repository_id: metadata.id, private: metadata.private, default_branch: defaultBranch, default_sha: sha };
      } else if (tool === "read_files") {
        const paths = input.paths;
        const ref = input.ref || defaultBranch;
        const files = [];
        let total = 0;
        for (const path of paths) {
          const content = await getFileAtRef(gh, path, ref);
          total += Buffer.byteLength(content, "utf8");
          if (total > MAX_TOTAL_BYTES) fail("payload_too_large", 413);
          files.push({ path, content });
        }
        result = { repository: metadata.full_name, ref, files };
      } else if (tool === "submit_change") {
        const id = requestId;
        const baseSha = input.expectedBaseSha;
        const title = input.title;
        const body = input.body;
        const files = input.files;
        const branch = `hermes/${id}`;
        const botLogin = await api.getAppBotLogin();
        let pull = await findPullByHead(gh, owner, branch, defaultBranch);
        if (pull) {
          validateManagedPull(pull, owner, repo, botLogin, defaultBranch);
          const currentBranchSha = await getRef(gh, branch);
          if (currentBranchSha !== pull.head.sha.toLowerCase()) fail("stale_head_sha", 409);
          if (pull.body?.includes(`hermes-request-id:${id}`) && await assertPayloadAtBranch(gh, files, branch)) {
            result = publicPull(pull);
          } else {
            fail("idempotency_conflict", 409);
          }
        } else {
          const existingSha = await optionalRef(gh, branch);
          const currentDefaultSha = await getRef(gh, defaultBranch);
          if (currentDefaultSha !== baseSha) fail("stale_base_sha", 409);
          if (existingSha === null) await ensureRef(gh, branch, baseSha, baseSha);
          else if (existingSha !== baseSha) {
            const existingCommit = await getCommit(gh, existingSha);
            if (existingCommit.message !== `Hermes proposal ${id}` || existingCommit.parents?.[0]?.sha?.toLowerCase() !== baseSha || !await assertPayloadAtBranch(gh, files, branch)) fail("idempotency_conflict", 409);
          }
          const branchSha = await getRef(gh, branch);
          if (branchSha === baseSha) {
            const commitSha = await createFeatureCommit(gh, files, baseSha, `Hermes proposal ${id}`);
            await updateRef(gh, branch, commitSha, baseSha);
          }
          if (await getRef(gh, defaultBranch) !== baseSha) fail("stale_base_sha", 409);
          pull = await findPullByHead(gh, owner, branch, defaultBranch);
          if (!pull) {
            try {
              pull = await gh.request("/pulls", { method: "POST", body: { title, body: `${body}\n\nhermes-request-id:${id}`, head: branch, base: defaultBranch, draft: true } });
            } catch (error) {
              if (!(error instanceof SafeError) || error.category !== "github_conflict") throw error;
              pull = await findPullByHead(gh, owner, branch, defaultBranch);
              if (!pull) throw error;
            }
          }
          validateManagedPull(pull, owner, repo, botLogin, defaultBranch);
          result = publicPull(pull);
        }
      } else if (tool === "revise_change") {
        const pullNumber = input.pullNumber;
        const expectedHead = input.expectedHeadSha;
        const id = requestId;
        const files = input.files;
        const botLogin = await api.getAppBotLogin();
        const pull = await getPull(gh, pullNumber);
        validateManagedPull(pull, owner, repo, botLogin, defaultBranch);
        const branch = pull.head.ref;
        const currentHead = await getRef(gh, branch);
        if (pull.head.sha?.toLowerCase() !== currentHead) fail("stale_head_sha", 409);
        if (currentHead !== expectedHead) {
          const currentCommit = await getCommit(gh, currentHead);
          if (currentCommit.message === `Hermes revision ${id}` && currentCommit.parents?.[0]?.sha?.toLowerCase() === expectedHead && await assertPayloadAtBranch(gh, files, branch)) {
            result = publicPull(pull);
          } else fail("stale_head_sha", 409);
        } else {
          const commitSha = await createFeatureCommit(gh, files, expectedHead, `Hermes revision ${id}`);
          await updateRef(gh, branch, commitSha, expectedHead);
          const updatedPull = await getPull(gh, pullNumber);
          validateManagedPull(updatedPull, owner, repo, botLogin, defaultBranch);
          result = publicPull(updatedPull);
        }
      } else if (tool === "change_status") {
        const pullNumber = input.pullNumber;
        const botLogin = await api.getAppBotLogin();
        const pull = await getPull(gh, pullNumber);
        validateManagedPull(pull, owner, repo, botLogin, defaultBranch);
        const combined = await gh.request(`/commits/${encodeURIComponent(pull.head.sha)}/status`);
        if (!isRecord(combined)) fail("github_invalid_response", 502);
        result = { ...publicPull(pull), commit_status: { state: combined.state, total_count: combined.total_count } };
      }
      status = "success";
      category = "none";
      return result;
    } catch (error) {
      category = error instanceof SafeError ? error.category : "internal_error";
      throw error instanceof SafeError ? error : new SafeError(category, 500);
    } finally {
      try {
        log({ tool, request_id: requestId, repository: `${owner}/${repo}`, status, latency_ms: Math.max(0, now() - started), category });
      } catch {
        // Logging failures must not expose or alter tool results.
      }
    }
  }

  return { invoke };
}

export function createLambdaHandler({ config, getPrivateKey, fetchImpl, log }) {
  const connector = createConnector({ config, getPrivateKey, fetchImpl, log });
  return async (event, context) => {
    const fullName = context?.clientContext?.custom?.bedrockAgentCoreToolName;
    const prefix = "github___";
    const tool = typeof fullName === "string" && fullName.startsWith(prefix) ? fullName.slice(prefix.length) : "";
    try {
      const result = await connector.invoke(tool, event);
      return { ok: true, result };
    } catch (error) {
      const category = error instanceof SafeError ? error.category : "internal_error";
      return { ok: false, error: { category } };
    }
  };
}

export const limits = Object.freeze({ MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES, MAX_API_BYTES });
export const toolNames = Object.freeze(Object.keys(TOOL_FIELDS));
