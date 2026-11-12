"""Skip deploying a tested commit once newer master commits change its inputs."""

import os
import re
import subprocess
import sys

SITES = ("oconnordev", "drumrollworld")


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def deployment_inputs(site):
    if site not in SITES:
        raise ValueError("Unknown site")
    inputs = [
        f"apps/{site}/",
        "scripts/ci/",
        "scripts/security/",
        "mise.toml",
        "mise.lock",
        "biome.json",
        f".github/workflows/{site}-site.yml",
        ".github/workflows/site.yml",
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
    return inputs


def verify(site, tested):
    inputs = deployment_inputs(site)
    if not re.fullmatch(r"[0-9a-f]{40}", tested):
        raise ValueError("Expected exact GitHub commit SHA")
    git("fetch", "--no-tags", "origin", tested)
    git("cat-file", "-e", f"{tested}^{{commit}}")
    git("fetch", "--no-tags", "origin", "+refs/heads/master:refs/ci/site-master")
    master = git("rev-parse", "refs/ci/site-master^{commit}")
    git("merge-base", "--is-ancestor", tested, master)
    changed = git("diff", "--name-only", tested, master, "--", *inputs)
    if not changed:
        print(f"Tested {tested}: {site} deployment inputs match master {master}")
        return True
    print(
        f"::notice title=Skipped {site} deploy::Skipped: newer master commit "
        f"{master} changes {site} deployment inputs and will deploy:\n{changed}"
    )
    return False


if __name__ == "__main__":
    try:
        deploy = verify(*sys.argv[1:])
    except (ValueError, TypeError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"deploy={str(deploy).lower()}\n")
