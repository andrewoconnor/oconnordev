import test from "node:test";
import assert from "node:assert/strict";
import { createConnector, SafeError, toolNames } from "../connector.mjs";

const OWNER = "andrewoconnor";
const REPO = "sample-repo";
const BASE = "a".repeat(40);
const SECRET_TOKEN = "ghs_synthetic_installation_token_never_return";
const OFFICIAL_TOOLS = ["create_branch", "create_pull_request", "get_file_contents", "list_branches", "pull_request_read", "push_files"];

class FakeGitHub {
  constructor() {
    this.metadata = { id: 12345, name: REPO, full_name: `${OWNER}/${REPO}`, private: true, default_branch: "main", owner: { login: OWNER, type: "User" } };
    this.branches = new Map([["main", BASE]]);
    this.commits = new Map([[BASE, { sha: BASE, tree: { sha: "tree-base" }, message: "base", parents: [], files: { "README.md": "base text\n", "src/app.py": "print('base')\n" } }]]);
    this.stagedTrees = new Map();
    this.pulls = [];
    this.tokenCalls = [];
    this.commitCounter = 1;
    this.identityMismatch = false;
  }
  async getInstallationToken(repository) { this.tokenCalls.push(repository); return SECRET_TOKEN; }
  async request(path, options = {}) {
    const method = options.method || "GET";
    const url = new URL(path, "https://api.github.com");
    const pathname = decodeURIComponent(url.pathname);
    const root = `/repos/${OWNER}/${REPO}`;
    if (pathname === root && method === "GET") {
      if (this.identityMismatch) return { ...this.metadata, owner: { login: OWNER, type: "Organization" } };
      return this.metadata;
    }
    if (pathname === `${root}/branches` && method === "GET") return [...this.branches.entries()].map(([name, sha]) => ({ name, commit: { sha } }));
    if (pathname.startsWith(`${root}/git/ref/heads/`) && method === "GET") {
      const branch = pathname.slice(`${root}/git/ref/heads/`.length);
      const sha = this.branches.get(branch);
      if (!sha) throw new SafeError("github_resource_not_found", 404);
      return { ref: `refs/heads/${branch}`, object: { sha } };
    }
    if (pathname === `${root}/git/refs` && method === "POST") {
      const branch = options.body.ref.replace(/^refs\/heads\//, "");
      if (this.branches.has(branch)) throw new SafeError("github_conflict", 409);
      this.branches.set(branch, options.body.sha);
      return { ref: options.body.ref, object: { sha: options.body.sha } };
    }
    if (pathname.startsWith(`${root}/git/refs/heads/`) && method === "PATCH") {
      const branch = pathname.slice(`${root}/git/refs/heads/`.length);
      if (!this.branches.has(branch)) throw new SafeError("github_resource_not_found", 404);
      this.branches.set(branch, options.body.sha);
      return { ref: `refs/heads/${branch}`, object: { sha: options.body.sha } };
    }
    if (pathname.startsWith(`${root}/git/commits/`) && method === "GET") {
      const commit = this.commits.get(pathname.slice(`${root}/git/commits/`.length));
      if (!commit) throw new SafeError("github_resource_not_found", 404);
      return commit;
    }
    if (pathname === `${root}/git/trees` && method === "POST") {
      const parent = [...this.commits.values()].find((commit) => commit.tree.sha === options.body.base_tree);
      if (!parent) throw new SafeError("github_resource_not_found", 404);
      const files = { ...parent.files };
      for (const file of options.body.tree) files[file.path] = file.content;
      const sha = `tree-${this.commitCounter}`;
      this.stagedTrees.set(sha, files);
      return { sha };
    }
    if (pathname === `${root}/git/commits` && method === "POST") {
      const sha = String(this.commitCounter++).padStart(40, "0");
      const parent = this.commits.get(options.body.parents[0]);
      const files = this.stagedTrees.get(options.body.tree) || parent.files;
      const commit = { sha, tree: { sha: options.body.tree }, message: options.body.message, parents: [{ sha: options.body.parents[0] }], files };
      this.commits.set(sha, commit);
      return commit;
    }
    if (pathname === `${root}/pulls` && method === "GET") {
      const head = url.searchParams.get("head");
      const branch = head?.split(":")[1];
      return this.pulls.filter((pull) => pull.state === "open" && pull.head.ref === branch && pull.base.ref === url.searchParams.get("base"));
    }
    if (pathname === `${root}/pulls` && method === "POST") {
      const branch = options.body.head;
      const pull = {
        id: 54321, number: this.pulls.length + 1, title: options.body.title, body: options.body.body, state: "open", draft: options.body.draft,
        html_url: `https://github.com/${OWNER}/${REPO}/pull/${this.pulls.length + 1}`, user: { login: "hermes-app[bot]" },
        base: { ref: options.body.base }, head: { ref: branch, sha: this.branches.get(branch), repo: { full_name: `${OWNER}/${REPO}` } },
      };
      this.pulls.push(pull);
      return pull;
    }
    const pullMatch = pathname.match(new RegExp(`^${root}/pulls/(\\d+)$`));
    if (pullMatch && method === "GET") {
      const pull = this.pulls[Number(pullMatch[1]) - 1];
      if (!pull) throw new SafeError("github_resource_not_found", 404);
      const sha = this.branches.get(pull.head.ref);
      if (options.accept === "application/vnd.github.diff") return `diff --git a/README.md b/README.md\n`;
      return { ...pull, head: { ...pull.head, sha } };
    }
    if (pathname.startsWith(`${root}/pulls/`) && pathname.endsWith("/files") && method === "GET") return [{ filename: "README.md", status: "modified" }];
    if (pathname.startsWith(`${root}/pulls/`) && pathname.endsWith("/commits") && method === "GET") return [{ sha: this.branches.get(this.pulls[0]?.head.ref) }];
    if (pathname.startsWith(`${root}/contents`) && method === "GET") {
      const filePath = pathname.slice(`${root}/contents`.length).replace(/^\//, "");
      const ref = url.searchParams.get("ref");
      const sha = this.branches.get(ref) || ref;
      const commit = this.commits.get(sha);
      if (!filePath) return Object.keys(commit?.files || {}).map((name) => ({ type: "file", name, path: name, size: Buffer.byteLength(commit.files[name]), sha: "blob-sha" }));
      const content = commit?.files?.[filePath];
      if (content === undefined) throw new SafeError("github_resource_not_found", 404);
      const bytes = Buffer.from(content, "utf8");
      return { type: "file", encoding: "base64", content: bytes.toString("base64"), size: bytes.length, sha: "blob-sha" };
    }
    if (pathname.startsWith(`${root}/commits/`) && pathname.endsWith("/check-runs") && method === "GET") return { total_count: 1, check_runs: [{ name: "CI", status: "completed", conclusion: "success" }] };
    if (pathname.startsWith(`${root}/commits/`) && pathname.endsWith("/status") && method === "GET") return { state: "success", total_count: 1 };
    throw new Error(`Unexpected fake request: ${method} ${pathname}`);
  }
}

function setup(options = {}) {
  const fake = options.fake || new FakeGitHub();
  const logs = [];
  const connector = createConnector({
    config: { appId: options.appId ?? "123456", installationId: options.installationId ?? "987654", allowedRepos: [REPO], owner: OWNER },
    getPrivateKey: options.getPrivateKey || (async () => "[REDACTED PRIVATE KEY]"),
    api: Object.hasOwn(options, "api") ? options.api : fake,
    log: (entry) => logs.push(entry),
    now: () => 1_700_000_000_000,
  });
  return { connector, fake, logs };
}
const repoArgs = (extra = {}) => ({ owner: OWNER, repo: REPO, ...extra });
async function createDraft(connector, branch = "hermes/test-123") {
  await connector.invoke("create_branch", repoArgs({ branch }));
  return connector.invoke("create_pull_request", repoArgs({ title: "Proposal", body: "Automated proposal", head: branch, base: "main", draft: true }));
}

test("exposes only the selected upstream GitHub MCP tool names", () => assert.deepEqual([...toolNames].sort(), OFFICIAL_TOOLS));
test("reads files and branch listings with upstream argument names", async () => {
  const { connector } = setup();
  const file = await connector.invoke("get_file_contents", repoArgs({ path: "README.md", ref: "main" }));
  assert.equal(file.content, "base text\n");
  assert.equal(file.path, "README.md");
  assert.equal((await connector.invoke("list_branches", repoArgs({ page: 1, perPage: 10 })))[0].name, "main");
});
test("list_branches honors upstream pagination within the 100-entry bound", async () => {
  const { connector, fake } = setup();
  for (let index = 0; index < 30; index += 1) fake.branches.set(`feature-${index}`, BASE);
  const branches = await connector.invoke("list_branches", repoArgs({ perPage: 100 }));
  assert.equal(branches.length, 31);
});
test("owner is fixed, repositories are allowlisted, and organization metadata fails closed", async () => {
  const { connector, fake } = setup();
  await assert.rejects(connector.invoke("get_file_contents", repoArgs({ owner: "some-org", path: "README.md" })), { category: "owner_not_allowed" });
  await assert.rejects(connector.invoke("get_file_contents", { owner: OWNER, repo: "other-repo", path: "README.md" }), { category: "repository_not_allowed" });
  fake.identityMismatch = true;
  await assert.rejects(connector.invoke("list_branches", repoArgs()), { category: "repository_identity_mismatch" });
});
test("creates approved branches only from the configured default branch", async () => {
  const { connector, fake } = setup();
  const result = await connector.invoke("create_branch", repoArgs({ branch: "hermes/official-tools", from_branch: "main" }));
  assert.equal(result.ref, "refs/heads/hermes/official-tools");
  assert.equal(fake.branches.get("hermes/official-tools"), BASE);
  await assert.rejects(connector.invoke("create_branch", repoArgs({ branch: "main", from_branch: "main" })), { category: "write_branch_not_allowed" });
  await assert.rejects(connector.invoke("create_branch", repoArgs({ branch: "hermes/not-default", from_branch: "other" })), { category: "write_base_not_allowed" });
});
test("push_files commits bounded changes only on approved feature branches", async () => {
  const { connector, fake } = setup();
  await connector.invoke("create_branch", repoArgs({ branch: "hermes/write-test" }));
  const result = await connector.invoke("push_files", repoArgs({ branch: "hermes/write-test", message: "Update docs", files: [{ path: "README.md", content: "new docs\n" }] }));
  assert.equal(fake.commits.get(fake.branches.get("hermes/write-test")).files["README.md"], "new docs\n");
  assert.equal(result.ref, "refs/heads/hermes/write-test");
  assert.equal(result.object.sha, fake.branches.get("hermes/write-test"));
  await assert.rejects(connector.invoke("push_files", repoArgs({ branch: "main", message: "not allowed", files: [{ path: "README.md", content: "no\n" }] })), { category: "write_branch_not_allowed" });
  await assert.rejects(connector.invoke("push_files", repoArgs({ branch: "hermes/write-test", message: "too many", files: Array.from({ length: 26 }, (_, i) => ({ path: `src/${i}.py`, content: "x" })) })), { category: "invalid_file_count" });
});
test("refuses writes even when the configured default branch matches the allowed feature prefix", async () => {
  const { connector, fake } = setup();
  fake.metadata.default_branch = "hermes/default";
  fake.branches.set("hermes/default", BASE);
  await assert.rejects(connector.invoke("push_files", repoArgs({ branch: "hermes/default", message: "must not write", files: [{ path: "README.md", content: "no\n" }] })), { category: "default_branch_write_denied" });
});
test("does not allow the default branch as a PR head even when it matches the feature prefix", async () => {
  const { connector, fake } = setup();
  fake.metadata.default_branch = "hermes/default";
  fake.branches.set("hermes/default", BASE);
  await assert.rejects(connector.invoke("create_pull_request", repoArgs({ title: "Self PR", head: "hermes/default", base: "hermes/default", draft: true })), { category: "default_branch_write_denied" });
});
test("create_pull_request always makes draft PRs on the default branch and rejects extra capabilities", async () => {
  const { connector, fake } = setup();
  const pr = await createDraft(connector, "hermes/pr-test");
  assert.equal(pr.id, "54321");
  assert.equal(pr.url, "https://github.com/andrewoconnor/sample-repo/pull/1");
  assert.equal(fake.pulls.length, 1);
  await assert.rejects(connector.invoke("create_pull_request", repoArgs({ title: "Not draft", head: "hermes/pr-test", base: "main", draft: false })), { category: "draft_required" });
  await assert.rejects(connector.invoke("create_pull_request", repoArgs({ title: "Wrong base", head: "hermes/pr-test", base: "other", draft: true })), { category: "pull_base_not_allowed" });
  await assert.rejects(connector.invoke("create_pull_request", repoArgs({ title: "Reviewer request", head: "hermes/pr-test", base: "main", draft: true, reviewers: ["some-team"] })), { category: "reviewers_not_allowed" });
  await assert.rejects(connector.invoke("create_pull_request", repoArgs({ title: "Maintainer write", head: "hermes/pr-test", base: "main", draft: true, maintainer_can_modify: true })), { category: "maintainer_modification_not_allowed" });
});
test("rejects non-boolean maintainer_can_modify values", async () => {
  const { connector } = setup();
  await connector.invoke("create_branch", repoArgs({ branch: "hermes/invalid-bool" }));
  await assert.rejects(connector.invoke("create_pull_request", repoArgs({ title: "Invalid type", head: "hermes/invalid-bool", base: "main", draft: true, maintainer_can_modify: "false" })), { category: "invalid_arguments" });
});

test("accepts an empty optional PR body as allowed by the upstream schema", async () => {
  const { connector, fake } = setup();
  await connector.invoke("create_branch", repoArgs({ branch: "hermes/empty-body" }));
  await connector.invoke("create_pull_request", repoArgs({ title: "Empty body", body: "", head: "hermes/empty-body", base: "main", draft: true }));
  assert.equal(fake.pulls[0].body, "");
});
test("pull_request_read supports only scoped read methods and paginates within bounds", async () => {
  const { connector } = setup();
  await createDraft(connector, "hermes/read-test");
  const call = (method, extra = {}) => connector.invoke("pull_request_read", repoArgs({ method, pullNumber: 1, ...extra }));
  assert.equal((await call("get")).draft, true);
  assert.match(await call("get_diff"), /diff --git/);
  assert.equal((await call("get_files", { page: 1, perPage: 20 }))[0].filename, "README.md");
  assert.ok((await call("get_commits"))[0].sha);
  assert.equal((await call("get_status")).state, "success");
  assert.equal((await call("get_check_runs")).check_runs[0].conclusion, "success");
  await assert.rejects(call("get_reviews"), { category: "pr_read_method_not_allowed" });
  await assert.rejects(call("get_comments"), { category: "pr_read_method_not_allowed" });
  await assert.rejects(call("get_files", { perPage: 101 }), { category: "invalid_arguments" });
});
test("rejects unsafe paths, unknown tools, legacy abstractions, and proxy arguments", async () => {
  const { connector, fake } = setup();
  await assert.rejects(connector.invoke("get_file_contents", repoArgs({ path: "../secret.md" })), { category: "invalid_path" });
  await assert.rejects(connector.invoke("get_file_contents", repoArgs({ path: ".env" })), { category: "unsupported_path" });
  await assert.rejects(connector.invoke("repository_info", {}), { category: "unknown_tool" });
  await assert.rejects(connector.invoke("graphql", {}), { category: "unknown_tool" });
  await assert.rejects(connector.invoke("get_file_contents", repoArgs({ path: "README.md", url: "https://api.github.com/" })), { category: "invalid_arguments" });
  assert.equal(fake.tokenCalls.length, 0);
});
test("does not expose credentials in tool results or logs", async () => {
  const { connector, logs } = setup();
  const result = await connector.invoke("get_file_contents", repoArgs({ path: "README.md" }));
  assert.equal(JSON.stringify(result).includes(SECRET_TOKEN), false);
  assert.equal(JSON.stringify(logs).includes(SECRET_TOKEN), false);
});
test("reports Secrets Manager failure without leaking provider details", async () => {
  const { connector } = setup({ api: null, getPrivateKey: async () => { throw new Error("synthetic secret value must not escape"); } });
  await assert.rejects(connector.invoke("get_file_contents", repoArgs({ path: "README.md" })), { category: "secrets_manager_failure" });
});
test("empty App identifiers disable every official tool before token or secret access", async () => {
  const { connector, fake } = setup({ appId: "", installationId: "" });
  await assert.rejects(connector.invoke("create_branch", repoArgs({ branch: "hermes/no-app" })), { category: "github_app_not_configured" });
  assert.equal(fake.tokenCalls.length, 0);
});
test("sanitizes GitHub authentication failures", async () => {
  const api = { async getInstallationToken() { throw new SafeError("github_authentication_failure", 502); }, async request() { throw new Error("must not run"); } };
  const { connector, logs } = setup({ api });
  await assert.rejects(connector.invoke("list_branches", repoArgs()), { category: "github_authentication_failure" });
  assert.equal(JSON.stringify(logs).includes(SECRET_TOKEN), false);
});
