import { SecretsManagerClient, GetSecretValueCommand } from "@aws-sdk/client-secrets-manager";
import { createLambdaHandler } from "./connector.mjs";

const region = process.env.AWS_REGION;
const secretArn = process.env.GITHUB_PRIVATE_KEY_ARN;
let cachedPrivateKey;
const secrets = new SecretsManagerClient({ region });

async function getPrivateKey() {
  if (cachedPrivateKey) return cachedPrivateKey;
  try {
    const value = await secrets.send(new GetSecretValueCommand({ SecretId: secretArn }));
    const key = typeof value.SecretString === "string"
      ? value.SecretString
      : value.SecretBinary
        ? Buffer.from(value.SecretBinary).toString("utf8")
        : "";
    if (!key.includes("-----BEGIN") || !key.includes("PRIVATE KEY-----")) throw new Error("invalid secret material");
    cachedPrivateKey = key;
    return key;
  } catch {
    // Do not forward SDK messages; they can include request metadata.
    throw new Error("secrets_manager_failure");
  }
}

let allowedRepos;
try {
  const parsed = JSON.parse(process.env.GITHUB_ALLOWED_REPOS || "[]");
  if (!Array.isArray(parsed) || parsed.some((item) => typeof item !== "string")) throw new Error("invalid allowlist");
  allowedRepos = parsed;
} catch {
  allowedRepos = [];
}

const handler = createLambdaHandler({
  config: {
    appId: process.env.GITHUB_APP_ID,
    installationId: process.env.GITHUB_INSTALLATION_ID,
    allowedRepos,
    owner: process.env.GITHUB_OWNER,
  },
  getPrivateKey,
});

export { handler };
