const OWNER = "andrewoconnor";
const MAX_FILES = 25;
const MAX_FILE_BYTES = 128 * 1024;
const MAX_TOTAL_BYTES = 512 * 1024;
const MAX_API_BYTES = 600 * 1024;
const GITHUB_API = "https://api.github.com";
const API_VERSION = "2022-11-28";
const OFFICIAL_TOOL_FIELDS = {
  get_file_contents: ["owner", "repo", "path", "ref", "sha", "fields"],
  list_branches: ["owner", "repo", "page", "perPage"],
  create_branch: ["owner", "repo", "branch", "from_branch"],
  push_files: ["owner", "repo", "branch", "files", "message"],
  create_pull_request: ["owner", "repo", "title", "body", "head", "base", "draft", "maintainer_can_modify", "reviewers"],
  pull_request_read: ["method", "owner", "repo", "pullNumber", "page", "perPage", "after"],
};
const OFFICIAL_TOOL_REQUIRED = {
  get_file_contents: ["owner", "repo"],
  list_branches: ["owner", "repo"],
  create_branch: ["owner", "repo", "branch"],
  push_files: ["owner", "repo", "branch", "files", "message"],
  create_pull_request: ["owner", "repo", "title", "head", "base"],
  pull_request_read: ["method", "owner", "repo", "pullNumber"],
};
const OFFICIAL_TOOL_NAMES = Object.freeze(Object.keys(OFFICIAL_TOOL_FIELDS));
const ALLOWED_PR_READ_METHODS = new Set(["get", "get_diff", "get_status", "get_files", "get_commits", "get_check_runs"]);
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

function validateRepositoryPath(value) {
  boundedString(value, 512);
  const path = value.replace(/^\/+/, "");
  if (!path) return "";
  if (path.includes("\\") || path.toLowerCase().includes("%2e") || path.split("/").some((part) => !part || part === "." || part === ".." || part.toLowerCase() === ".git")) fail("invalid_path");
  if (/\.(?:env|pem|key|p12|pfx|crt|cer|tfstate|secret|secrets)(?:\.|$)/i.test(path) || path.split("/").some((part) => part === ".env")) fail("unsupported_path");
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

  async function request(path, { method = "GET", token, jwt, body, accept = "application/vnd.github+json", responseType = "json" } = {}) {
    if (!path.startsWith("/") || path.startsWith("//") || path.includes("..")) fail("github_request_rejected", 500);
    const url = new URL(path, GITHUB_API);
    if (url.origin !== GITHUB_API) fail("github_request_rejected", 500);
    const headers = {
      Accept: accept,
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
    if (responseType === "text") return text;
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
  return gh.request(`/git/ref/heads/${encodeRef(branch)}`);
}

function publicPull(pull) {
  if (!isRecord(pull) || !Number.isSafeInteger(pull.id) || typeof pull.html_url !== "string" || pull.html_url.length > 2048) fail("github_invalid_response", 502);
  return { id: String(pull.id), url: pull.html_url };
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

  function validateWriteBranch(value) {
    const branch = validateRef(value);
    if (!branch.startsWith("hermes/") || branch.length <= "hermes/".length) fail("write_branch_not_allowed", 403);
    return branch;
  }

  function validatePagination(args) {
    if (args.page !== undefined && (!Number.isSafeInteger(args.page) || args.page < 1)) fail("invalid_arguments");
    if (args.perPage !== undefined && (!Number.isSafeInteger(args.perPage) || args.perPage < 1 || args.perPage > 100)) fail("invalid_arguments");
  }

  async function invokeOfficial(tool, rawArgs) {
    const fields = OFFICIAL_TOOL_FIELDS[tool];
    exactKeys(rawArgs, fields, OFFICIAL_TOOL_REQUIRED[tool]);
    if (rawArgs.owner !== OWNER) fail("owner_not_allowed", 403);
    const repo = validateRepoName(rawArgs.repo, allowedRepos);
    if (tool === "get_file_contents") {
      const rawPath = rawArgs.path === undefined ? "/" : boundedString(rawArgs.path, 512);
      const path = validateRepositoryPath(rawPath);
      const ref = rawArgs.sha === undefined ? (rawArgs.ref === undefined ? null : validateRef(rawArgs.ref)) : validateSha(rawArgs.sha);
      const allowedFields = new Set(["type", "name", "path", "size", "sha", "url", "git_url", "html_url", "download_url"]);
      if (rawArgs.fields !== undefined && (!Array.isArray(rawArgs.fields) || rawArgs.fields.length > allowedFields.size || rawArgs.fields.some((field) => typeof field !== "string" || !allowedFields.has(field)) || new Set(rawArgs.fields).size !== rawArgs.fields.length)) fail("invalid_arguments");
      const token = await tokenFor(repo);
      const metadata = await getRepository(api, token, OWNER, repo);
      const gh = createToolClient(api, token, OWNER, repo);
      const resolvedRef = ref || metadata.default_branch;
      const query = new URLSearchParams({ ref: resolvedRef });
      const document = await gh.request(`/contents${path ? `/${encodePath(path)}` : ""}?${query.toString()}`);
      if (Array.isArray(document)) {
        const entries = document.slice(0, MAX_FILES).map((entry) => {
          if (!isRecord(entry)) fail("github_invalid_response", 502);
          const fields = rawArgs.fields || [...allowedFields];
          return Object.fromEntries(fields.filter((field) => Object.hasOwn(entry, field)).map((field) => [field, entry[field]]));
        });
        return { path, ref: resolvedRef, entries, truncated: document.length > MAX_FILES };
      }
      if (!isRecord(document) || document.type !== "file") fail("unsupported_file_type", 415);
      const safePath = validatePath(path);
      if (typeof document.content !== "string" || document.encoding !== "base64" || !Number.isSafeInteger(document.size) || document.size < 0 || document.size > MAX_FILE_BYTES) fail("file_too_large", 413);
      const bytes = Buffer.from(document.content.replace(/\\s+/g, ""), "base64");
      if (bytes.length !== document.size || bytes.length > MAX_FILE_BYTES) fail("github_invalid_response", 502);
      const content = bytes.toString("utf8");
      if (Buffer.from(content, "utf8").compare(bytes) !== 0 || content.includes("\\0")) fail("binary_content_not_supported", 415);
      return { path: safePath, ref: resolvedRef, sha: document.sha, size: bytes.length, content };
    }
    if (tool === "list_branches") {
      validatePagination(rawArgs);
      const token = await tokenFor(repo);
      await getRepository(api, token, OWNER, repo);
      const perPage = rawArgs.perPage ?? 30;
      const page = rawArgs.page ?? 1;
      const branches = await createToolClient(api, token, OWNER, repo).request(`/branches?${new URLSearchParams({ page: String(page), per_page: String(perPage) }).toString()}`);
      if (!Array.isArray(branches)) fail("github_invalid_response", 502);
      if (branches.length > 100) return branches.slice(0, 100);
      return branches;
    }
    if (tool === "pull_request_read") {
      validatePagination(rawArgs);
      if (!ALLOWED_PR_READ_METHODS.has(rawArgs.method)) fail("pr_read_method_not_allowed", 403);
      if (rawArgs.after !== undefined) fail("pr_cursor_not_supported", 400);
      const pullNumber = validatePullNumber(rawArgs.pullNumber);
      const token = await tokenFor(repo);
      await getRepository(api, token, OWNER, repo);
      const gh = createToolClient(api, token, OWNER, repo);
      const method = rawArgs.method;
      if (method === "get_diff") return gh.request(`/pulls/${pullNumber}`, { accept: "application/vnd.github.diff", responseType: "text" });
      const pull = await getPull(gh, pullNumber);
      if (method === "get") return pull;
      if (typeof pull.head?.sha !== "string" || !/^[a-f0-9]{40}$/i.test(pull.head.sha)) fail("github_invalid_response", 502);
      if (method === "get_status") return gh.request(`/commits/${encodeURIComponent(pull.head.sha)}/status`);
      const page = rawArgs.page ?? 1;
      const perPage = rawArgs.perPage ?? 30;
      if (method === "get_files") return gh.request(`/pulls/${pullNumber}/files?${new URLSearchParams({ page: String(page), per_page: String(perPage) }).toString()}`);
      if (method === "get_commits") return gh.request(`/pulls/${pullNumber}/commits?${new URLSearchParams({ page: String(page), per_page: String(perPage) }).toString()}`);
      return gh.request(`/commits/${encodeURIComponent(pull.head.sha)}/check-runs?${new URLSearchParams({ page: String(page), per_page: String(perPage) }).toString()}`);
    }
    if (tool === "create_pull_request") {
      const branch = validateWriteBranch(rawArgs.head);
      if (rawArgs.draft !== true) fail("draft_required", 403);
      if (rawArgs.base !== undefined && (typeof rawArgs.base !== "string" || rawArgs.base.length > 255)) fail("invalid_arguments");
      if (rawArgs.maintainer_can_modify !== undefined && typeof rawArgs.maintainer_can_modify !== "boolean") fail("invalid_arguments");
      if (rawArgs.maintainer_can_modify === true) fail("maintainer_modification_not_allowed", 403);
      if (rawArgs.reviewers !== undefined && (!Array.isArray(rawArgs.reviewers) || rawArgs.reviewers.length > 0)) fail("reviewers_not_allowed", 403);
      const title = boundedString(rawArgs.title, 256);
      if (rawArgs.body !== undefined && (typeof rawArgs.body !== "string" || rawArgs.body.length > 5000 || rawArgs.body.includes("\0"))) fail("invalid_arguments");
      const body = rawArgs.body ?? "";
      const started = now();
      let category = "internal_error";
      try {
        if (!appId || !installationId) fail("github_app_not_configured", 503);
        const token = await tokenFor(repo);
        const metadata = await getRepository(api, token, OWNER, repo);
        if (branch === metadata.default_branch) fail("default_branch_write_denied", 403);
        if (rawArgs.base !== metadata.default_branch) fail("pull_base_not_allowed", 403);
        const gh = createToolClient(api, token, OWNER, repo);
        await getRef(gh, branch);
        if (await findPullByHead(gh, OWNER, branch, metadata.default_branch)) fail("github_conflict", 409);
        const pull = await gh.request("/pulls", { method: "POST", body: {
          title, body, head: branch, base: metadata.default_branch, draft: true, maintainer_can_modify: false,
        } });
        if (!isRecord(pull) || pull.draft !== true || pull.base?.ref !== metadata.default_branch || pull.head?.ref !== branch) fail("github_invalid_response", 502);
        category = "none";
        return publicPull(pull);
      } catch (error) {
        category = error instanceof SafeError ? error.category : "internal_error";
        throw error instanceof SafeError ? error : new SafeError(category, 500);
      } finally {
        try { log({ tool, repository: `${OWNER}/${repo}`, status: category === "none" ? "success" : "error", latency_ms: Math.max(0, now() - started), category }); } catch { /* no sensitive data */ }
      }
    }
    if (tool === "push_files") {
      const branch = validateWriteBranch(rawArgs.branch);
      const files = validateFiles(rawArgs.files);
      const message = boundedString(rawArgs.message, 256);
      const started = now();
      let category = "internal_error";
      try {
        if (!appId || !installationId) fail("github_app_not_configured", 503);
        const token = await tokenFor(repo);
        const metadata = await getRepository(api, token, OWNER, repo);
        if (branch === metadata.default_branch) fail("default_branch_write_denied", 403);
        const gh = createToolClient(api, token, OWNER, repo);
        const parentSha = await getRef(gh, branch);
        const sha = await createFeatureCommit(gh, files, parentSha, message);
        const updatedRef = await updateRef(gh, branch, sha);
        category = "none";
        return updatedRef;
      } catch (error) {
        category = error instanceof SafeError ? error.category : "internal_error";
        throw error instanceof SafeError ? error : new SafeError(category, 500);
      } finally {
        try { log({ tool, repository: `${OWNER}/${repo}`, status: category === "none" ? "success" : "error", latency_ms: Math.max(0, now() - started), category }); } catch { /* no sensitive data */ }
      }
    }
    if (tool === "create_branch") {
      const branch = validateWriteBranch(rawArgs.branch);
      if (rawArgs.from_branch !== undefined) validateRef(rawArgs.from_branch);
      const started = now();
      let category = "internal_error";
      try {
        if (!appId || !installationId) fail("github_app_not_configured", 503);
        const token = await tokenFor(repo);
        const metadata = await getRepository(api, token, OWNER, repo);
        if (rawArgs.from_branch !== undefined && rawArgs.from_branch !== metadata.default_branch) fail("write_base_not_allowed", 403);
        const gh = createToolClient(api, token, OWNER, repo);
        const baseSha = await getRef(gh, metadata.default_branch);
        if (await optionalRef(gh, branch) !== null) fail("github_conflict", 409);
        const result = await gh.request("/git/refs", { method: "POST", body: { ref: `refs/heads/${branch}`, sha: baseSha } });
        category = "none";
        return result;
      } catch (error) {
        category = error instanceof SafeError ? error.category : "internal_error";
        throw error instanceof SafeError ? error : new SafeError(category, 500);
      } finally {
        try { log({ tool, repository: `${OWNER}/${repo}`, status: category === "none" ? "success" : "error", latency_ms: Math.max(0, now() - started), category }); } catch { /* no sensitive data */ }
      }
    }
    fail("tool_not_implemented", 501);
  }

  async function invoke(tool, rawArgs) {
    if (!Object.hasOwn(OFFICIAL_TOOL_FIELDS, tool)) fail("unknown_tool", 404);
    return invokeOfficial(tool, rawArgs);
  }

  return { invoke, toolNames: OFFICIAL_TOOL_NAMES };
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
export const toolNames = OFFICIAL_TOOL_NAMES;
