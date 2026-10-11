# oconnor.dev resume release

Hosting now lives in `infra/aws/oconnordev` / Spacelift `oconnordev-resume`, using the shared local static-site module. Before any infrastructure apply, complete the [mandatory state handoff](../static-site-state-migration.md). Production retains the shared wildcard certificate and hosted zone for Hermes MCP.

## Build and validate

From the repository root, use the versions pinned in `mise.toml`/`mise.lock`:

```sh
mise run fmt:site
mise run lint:site
mise run build:oconnordev
mise run test:oconnordev
mise exec -- python -m unittest scripts.ci.tests.test_static_site_deployment -v
mise run workflow-lint
```

The build performs `npm ci --ignore-scripts` against the committed lockfile.
Locally it uses `/usr/bin/chromium` if present; `CHROMIUM_PATH` can select an
existing executable. Without either, install the locked Playwright browser:

```sh
npm --prefix apps/oconnordev exec --no -- playwright install chromium --only-shell
```

CI installs Playwright's matching Chromium headless shell and OS dependencies before
rendering, and uses it instead of any system Chromium.
The generated release in `apps/oconnordev/dist/` contains only `index.html`, `404.html`,
`assets/css/resume-<sha256>.css`, `favicon.ico`, `assets/resume-preview.png`, and
`resume.pdf`. Never sync the source directory or `node_modules`.

Tests open a local HTTP server, block foreign browser requests, check semantic
headings/lists, metadata, keyboard focus, contrast and mobile overflow, and
compare every resume section against `resume-content.json` captured from baseline
`6aaf603`. Update that fixture only for separately approved resume-content changes.
PDF.js parses the actual PDF to check one page, every section, identity, link
annotations, readable font sizes and text coordinates within page margins.
A browser download is byte-compared with the generated PDF; the preview's PNG
signature and 1200×630 dimensions are checked.

## Release and rollback

Pull requests validate without AWS credentials. The check job builds/lints/tests
`github.sha` once and uploads the tested dist as a pinned same-run artifact.
Deployment downloads it without rebuilding, verifies SHA256 before credentials,
and rejects a tested SHA that no longer equals remote master. The
`oconnordev-production` environment restricts deployments to branch master;
its exact environment subject can assume only the OConnorDev broker/site-role
chain. [User-owned IAM/environment bootstrap](infrastructure-bootstrap.md#tested-artifact-environment-cutover)
must finish before merging the auto-deploy cutover. No runtime or hosting changes
are required, but the trust/environment configuration **does require apply**.

After deployment, verify the canonical page, contact links, `/resume.pdf` download
and `/assets/resume-preview.png` plus a real missing-path HTTP 404 at `https://oconnor.dev/`; verify the PDF opens
as one page and the preview returns `image/png`. Social services may retain
cached previews. For rollback, revert the approved change on master and use the
same gated release workflow; do not upload development sources manually.

## Mobile icons and stylesheet cache consistency

Serving the pre-icon CSS from baseline `6aaf603` with the newer inline SVG HTML
reproduces oversized icons in Chromium: at a 390px viewport they measure about
375.61×375.61px instead of 12×12px. Fresh CSS does not reproduce the failure.
This demonstrates a stale-stylesheet failure mode matching the reported screenshot;
it does not confirm the user's device cache state or a Safari engine defect.
Safari/iPhone rendering has not been tested here.

All six decorative SVGs carry `width="1em"` and `height="1em"` presentation
attributes as a fallback alongside CSS sizing. Browser tests intercept the CSS
response and remove just the icon rule to reproduce the stale sizing dependency,
then assert actual icon and contact-text geometry at 375/390px, desktop and print.
The build hashes the exact CSS bytes using Node's SHA-256 and rewrites only the
built HTML's stylesheet URL; source HTML keeps `/assets/css/resume.css` readable.
The release test validates the href against the actual asset hash and allowlist.

Deployment uploads assets first, once per file with final cache metadata.
Only the content-hashed CSS is immutable; HTML, PDF, preview and stable assets
use `public,max-age=0,must-revalidate`. The final root deletion pass uses
`--delete --size-only --exclude "assets/*" --exclude "images/*"`, skipping current
files already uploaded at equal size and retaining all prior hashed CSS for cached
HTML. Do not delete older assets during ordinary releases/rollback. No sources
are uploaded; PDF rendering and runtime behavior are unchanged.

## Continuous PDF limitations

The visible PDF link downloads a prebuilt PDF without JavaScript. It is a single
custom-height page at normal 12pt body size, measured in print media at an 8.5in
width with 0.5in margins, not a resume squeezed onto Letter. It is intended for
continuous on-screen scrolling. Some viewers initially fit the entire tall page
into the window; select fit-width or zoom in. Printer drivers may tile, paginate,
clip, or scale a tall custom page. Ordinary browser paper printing can paginate;
this is separate from the one-page downloadable PDF. Rebuild after content or CSS
changes. System-font metrics and rendering may differ across operating systems;
CI uses the lockfile-matched browser, and validates the generated result.

The site uses system fonts, decorative inline SVG icons, local CSS and no runtime
scripts. This removes third-party font/script subresource requests and permits a
restrictive CSP as a separate delivery-policy decision; it is not a legal/privacy
compliance guarantee. Person metadata uses existing resume claims and the supplied
LinkedIn URL; the preview is a text-only brand card, not a portrait.
