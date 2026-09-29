import test from "node:test";
import assert from "node:assert/strict";
import { createConnector, SafeError } from "../connector.mjs";

const OWNER = "andrewoconnor";
const REPO = "sample-repo";
const BASE = "a".repeat(40);
const SECRET_TOKEN = "ghs_synthetic_installation_token_never_return";

class FakeGitHub {
  constructor() {
    this.metadata = {
      id: 12345,
      name: REPO,
      full_name: `${OWNER}/${REPO}`,
      private: true,
      default_branch: "main",
      owner: { login: OWNER, type: "User" },
    };
    this.branches = new Map([["main", BASE]]);
    this.trees = new Map([["tree-base", { "README.md": "base text\n", "src/app.py": "print('base')\n" }]]);
    this.commits = new Map([[BASE, { sha: BASE, tree: { sha: "tree-base" }, message: "base", parents: [], files: this.trees.get("tree-base") }]]);
    this.stagedTrees = new Map();
    this.pulls = [];
    this.tokenCalls = [];
    this.commitCounter = 1;
    this.identityMismatch = false;
    this.failAfterPullCreateOnce = false;
  }

  async getInstallationToken(repository) {
    this.tokenCalls.push(repository);
    return SECRET_TOKEN;
  }

  async getAppBotLogin() {
    return "hermes-app[bot]";
  }

  async request(path, options = {}) {
    const method = options.method || "GET";
    const url = new URL(path, "https://api.github.com");
    const pathname = decodeURIComponent(url.pathname);
    const root = `/repos/${OWNER}/${REPO}`;
    if (pathname === root && method === "GET") {
      if (this.identityMismatch) return { ...this.metadata, owner: { login: OWNER, type: "Organization" } };
      return this.metadata;
    }
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
      const sha = pathname.slice(`${root}/git/commits/`.length);
      const commit = this.commits.get(sha);
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
        number: this.pulls.length + 1,
        title: options.body.title,
        body: options.body.body,
        state: "open",
        draft: options.body.draft,
        html_url: `https://github.com/${OWNER}/${REPO}/pull/${this.pulls.length + 1}`,
        user: { login: "hermes-app[bot]" },
        base: { ref: options.body.base },
        head: { ref: branch, sha: this.branches.get(branch), repo: { full_name: `${OWNER}/${REPO}` } },
      };
      this.pulls.push(pull);
      if (this.failAfterPullCreateOnce) {
        this.failAfterPullCreateOnce = false;
        throw new SafeError("github_transport_failure", 502);
      }
      return pull;
    }
    const pullMatch = pathname.match(new RegExp(`^${root}/pulls/(\\d+)$`));
    if (pullMatch && method === "GET") {
      const pull = this.pulls[Number(pullMatch[1]) - 1];
      if (!pull) throw new SafeError("github_resource_not_found", 404);
      const sha = this.branches.get(pull.head.ref);
      return { ...pull, head: { ...pull.head, sha } };
    }
    if (pathname.startsWith(`${root}/contents/`) && method === "GET") {
      const filePath = pathname.slice(`${root}/contents/`.length);
      const ref = url.searchParams.get("ref");
      const sha = this.branches.get(ref) || ref;
      const commit = this.commits.get(sha);
      const content = commit?.files?.[filePath];
      if (content === undefined) throw new SafeError("github_resource_not_found", 404);
      const bytes = Buffer.from(content, "utf8");
      return { type: "file", encoding: "base64", content: bytes.toString("base64"), size: bytes.length };
    }
    if (pathname.startsWith(`${root}/commits/`) && pathname.endsWith("/status") && method === "GET") {
      return { state: "success", total_count: 1 };
    }
    throw new Error(`Unexpected fake request: ${method} ${pathname}`);
  }
}

function setup(options = {}) {
  const fake = options.fake || new FakeGitHub();
  const logs = [];
  const connector = createConnector({
    config: { appId: "123456", installationId: "987654", allowedRepos: [REPO], owner: OWNER },
    getPrivateKey: options.getPrivateKey || (async () => "-----BEGIN PRIVATE KEY-----synthetic-----END PRIVATE KEY-----"),
    api: Object.hasOwn(options, "api") ? options.api : fake,
    log: (entry) => logs.push(entry),
    now: () => 1_700_000_000_000,
  });
  return { connector, fake, logs };
}

const args = (extra = {}) => ({ repository: REPO, ...extra });

async function submit(connector, extra = {}) {
  return connector.invoke("submit_change", args({
    request_id: "test-123",
    expected_base_sha: BASE,
    title: "Add a harmless change",
    body: "Automated proposal",
    files: [{ path: "README.md", content: "updated\n" }],
    ...extra,
  }));
}

test("allowlisted personal repository metadata and reads work", async () => {
  const { connector } = setup();
  const info = await connector.invoke("repository_info", args());
  assert.equal(info.repository, `${OWNER}/${REPO}`);
  assert.equal(info.default_sha, BASE);
  const files = await connector.invoke("read_files", args({ paths: ["README.md", "src/app.py"] }));
  assert.equal(files.files.length, 2);
  assert.equal(files.files[0].content, "base text\n");
});

test("rejects unallowlisted names, caller-supplied owners, and non-personal GitHub metadata", async () => {
  const { connector, fake } = setup();
  await assert.rejects(connector.invoke("repository_info", { repository: "other-repo" }), { category: "repository_not_allowed" });
  await assert.rejects(connector.invoke("repository_info", { repository: REPO, owner: "some-org" }), { category: "invalid_arguments" });
  fake.identityMismatch = true;
  await assert.rejects(connector.invoke("repository_info", args()), { category: "repository_identity_mismatch" });
});

test("creates a deterministic feature branch and draft pull request", async () => {
  const { connector, fake } = setup();
  const result = await submit(connector);
  assert.equal(result.draft, true);
  assert.equal(result.base_branch, "main");
  assert.equal(result.branch, "hermes/test-123");
  assert.equal(fake.pulls.length, 1);
  assert.equal(fake.branches.get("main"), BASE);
});

test("rejects stale base SHA before creating a branch", async () => {
  const { connector, fake } = setup();
  fake.branches.set("main", "b".repeat(40));
  await assert.rejects(submit(connector), { category: "stale_base_sha" });
  assert.equal(fake.branches.has("hermes/test-123"), false);
});

test("revision requires and uses the current expected head SHA", async () => {
  const { connector } = setup();
  const pr = await submit(connector);
  const revision = await connector.invoke("revise_change", args({
    pull_number: pr.number,
    request_id: "revision-1",
    expected_head_sha: pr.head_sha,
    files: [{ path: "README.md", content: "revised\n" }],
  }));
  assert.equal(revision.draft, true);
  assert.notEqual(revision.head_sha, pr.head_sha);
  await assert.rejects(connector.invoke("revise_change", args({
    pull_number: pr.number,
    request_id: "revision-2",
    expected_head_sha: pr.head_sha,
    files: [{ path: "README.md", content: "stale\n" }],
  })), { category: "stale_head_sha" });
});

test("rejects unknown tools and arbitrary REST, URL, or GraphQL proxy arguments", async () => {
  const { connector, fake } = setup();
  await assert.rejects(connector.invoke("graphql", {}), { category: "unknown_tool" });
  await assert.rejects(connector.invoke("repository_info", args({ url: "https://api.github.com/repos/andrewoconnor/sample-repo" })), { category: "invalid_arguments" });
  await assert.rejects(connector.invoke("repository_info", args({ query: "{ viewer { login } }" })), { category: "invalid_arguments" });
  assert.equal(fake.tokenCalls.length, 0);
});

test("rejects traversal and unsupported file paths", async () => {
  const { connector } = setup();
  await assert.rejects(connector.invoke("read_files", args({ paths: ["../secret.txt"] })), { category: "invalid_path" });
  await assert.rejects(connector.invoke("read_files", args({ paths: [".env"] })), { category: "unsupported_file_type" });
});

test("rejects oversized write payloads", async () => {
  const { connector } = setup();
  await assert.rejects(submit(connector, { files: [{ path: "README.md", content: "x".repeat(128 * 1024 + 1) }] }), { category: "file_too_large" });
});

test("never includes a synthetic installation token in a tool response or logs", async () => {
  const { connector, logs } = setup();
  const result = await connector.invoke("repository_info", args());
  assert.equal(JSON.stringify(result).includes(SECRET_TOKEN), false);
  assert.equal(JSON.stringify(logs).includes(SECRET_TOKEN), false);
});

test("reports Secrets Manager failure without exposing provider details", async () => {
  const { connector } = setup({ api: null, getPrivateKey: async () => { throw new Error("synthetic secret value must not escape"); } });
  await assert.rejects(connector.invoke("repository_info", args()), { category: "secrets_manager_failure" });
});

test("sanitizes GitHub authentication failure", async () => {
  const api = {
    async getInstallationToken() { throw new SafeError("github_authentication_failure", 502); },
    async request() { throw new Error("must not be called"); },
    async getAppBotLogin() { return "hermes-app[bot]"; },
  };
  const { connector, logs } = setup({ api });
  await assert.rejects(connector.invoke("repository_info", args()), { category: "github_authentication_failure" });
  assert.equal(JSON.stringify(logs).includes(SECRET_TOKEN), false);
  assert.equal(logs[0].category, "github_authentication_failure");
});

test("recovers idempotently when PR creation succeeds remotely but the response is lost", async () => {
  const { connector, fake } = setup();
  fake.failAfterPullCreateOnce = true;
  await assert.rejects(submit(connector), { category: "github_transport_failure" });
  const result = await submit(connector);
  assert.equal(result.draft, true);
  assert.equal(fake.pulls.length, 1);
  assert.equal(fake.branches.size, 2);
});

test("change_status only returns safe draft status metadata", async () => {
  const { connector } = setup();
  const pr = await submit(connector);
  const result = await connector.invoke("change_status", args({ pull_number: pr.number }));
  assert.equal(result.commit_status.state, "success");
  assert.equal(result.commit_status.total_count, 1);
});
