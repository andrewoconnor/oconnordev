"""Reject changed deployment inputs, without replacing the tested checkout."""

import re
import subprocess
import sys


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def verify(site, tested):
    if site not in ("oconnordev", "drumrollworld"):
        raise ValueError("Unknown site")
    if not re.fullmatch(r"[0-9a-f]{40}", tested):
        raise ValueError("Expected exact GitHub commit SHA")
    git("fetch", "--no-tags", "origin", tested)
    git("cat-file", "-e", f"{tested}^{{commit}}")
    git("fetch", "--no-tags", "origin", "+refs/heads/master:refs/ci/site-master")
    master = git("rev-parse", "refs/ci/site-master^{commit}")
    inputs = [
        f"apps/{site}/",
        "scripts/ci/",
        "scripts/security/",
        "mise.toml",
        "mise.lock",
        "biome.json",
        f".github/workflows/{site}-site.yml",
        f"infra/aws/{site}/site.tf",
        "infra/modules/static-site/",
    ]
    if site == "drumrollworld":
        inputs.extend(
            [
                "scripts/drumrollworld/",
                "docs/assets/drumrollworld-published-assets.json",
            ]
        )
    changed = git("diff", "--name-only", tested, master, "--", *inputs)
    if changed:
        raise ValueError(f"Stale tested {site} deployment inputs:\n{changed}")
    print(f"Tested {tested}: {site} deployment inputs match master {master}")


if __name__ == "__main__":
    try:
        verify(*sys.argv[1:])
    except (ValueError, TypeError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
