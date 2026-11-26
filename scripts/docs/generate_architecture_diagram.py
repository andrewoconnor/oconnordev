from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "docs/architecture/overview.svg"

W, H = 1800, 1330
S = 56
FONT = "Helvetica, Arial, sans-serif"
INK = "#232F3E"
LINE = "#545B64"
MUTED = "#687078"
PINK = "#E7157B"
RED = "#DD344C"
PURPLE = "#8C4FFF"
GREEN = "#7AA116"
ORANGE = "#ED7100"
TEAL = "#01A88D"
HALO = {"stroke": "#fff", "stroke_width": 4, "paint_order": "stroke"}

out = []


def attrs(**kw):
    return "".join(f' {k.replace("_", "-")}="{v}"' for k, v in kw.items())


def el(tag, body=None, **kw):
    if body is None:
        return f"<{tag}{attrs(**kw)}/>"
    return f"<{tag}{attrs(**kw)}>{body}</{tag}>"


def stroke_group(x, y, color, width, body):
    return el(
        "g",
        body,
        transform=f"translate({x},{y})",
        fill="none",
        stroke=color,
        stroke_width=width,
        stroke_linecap="round",
        stroke_linejoin="round",
    )


def glyph_text(x, y, size, s):
    return el(
        "text",
        s,
        x=x,
        y=y,
        font_size=size,
        font_weight=700,
        fill="#fff",
        stroke="none",
        text_anchor="middle",
        font_family=FONT,
    )


TILES = {
    "cloudfront": (
        PURPLE,
        '<circle cx="28" cy="28" r="16"/>'
        '<ellipse cx="28" cy="28" rx="7" ry="16"/>'
        '<path d="M12 28h32"/>'
        '<circle cx="28" cy="12" r="2.5" fill="#fff"/>'
        '<circle cx="42" cy="34" r="2.5" fill="#fff"/>'
        '<circle cx="16" cy="38" r="2.5" fill="#fff"/>',
    ),
    "s3": (
        GREEN,
        '<ellipse cx="28" cy="17" rx="15" ry="5"/>'
        '<path d="M13 17l4 24c1 3 21 3 22 0l4-24"/>',
    ),
    "route53": (
        PURPLE,
        '<path d="M28 10l15 6v10c0 10-7 17-15 20-8-3-15-10-15-20V16z"/>'
        + glyph_text(28, 34, 13, "53"),
    ),
    "lambda": (ORANGE, '<path d="M17 43h7l7-14 5 14h5M20 13h6l12 30"/>'),
    "cognito": (
        RED,
        '<rect x="11" y="15" width="34" height="26" rx="2"/>'
        '<circle cx="21" cy="25" r="4"/>'
        '<path d="M14 36c1-4 4-6 7-6s6 2 7 6M32 23h9M32 29h9M32 35h6"/>',
    ),
    "gateway": (
        TEAL,
        '<circle cx="28" cy="28" r="6"/>'
        '<circle cx="12" cy="14" r="3"/><circle cx="44" cy="14" r="3"/>'
        '<circle cx="12" cy="42" r="3"/><circle cx="44" cy="42" r="3"/>'
        '<path d="M15 16l8 8M41 16l-8 8M15 40l8-8M41 40l-8-8"/>',
    ),
    "identity": (
        TEAL,
        '<circle cx="22" cy="20" r="6"/>'
        '<path d="M11 40c1-7 5-11 11-11 3 0 5 1 7 2"/>'
        '<circle cx="37" cy="36" r="5"/><path d="M37 41v6M37 44h3"/>',
    ),
    "athena": (
        PURPLE,
        '<circle cx="25" cy="25" r="11"/><path d="M33 33l10 10"/>'
        '<path d="M19 29v-4M25 29v-8M31 29v-6"/>',
    ),
    "cloudtrail": (
        PINK,
        '<path d="M17 36h-1a7 7 0 010-14 10 10 0 0119-3 8 8 0 015 17h-3"/>'
        '<path d="M20 34h16M23 40h10M26 46h4"/>',
    ),
    "config": (
        PINK,
        '<path d="M16 12v32M28 12v32M40 12v32"/>'
        '<rect x="12" y="18" width="8" height="6" fill="#fff"/>'
        '<rect x="24" y="32" width="8" height="6" fill="#fff"/>'
        '<rect x="36" y="22" width="8" height="6" fill="#fff"/>',
    ),
    "cloudwatch": (
        PINK,
        '<path d="M18 38h-2a8 8 0 010-16 11 11 0 0121-3 9 9 0 016 9"/>'
        '<circle cx="34" cy="34" r="6"/><path d="M38 38l6 6"/>',
    ),
    "organizations": (
        PINK,
        '<rect x="22" y="10" width="12" height="10"/>'
        '<rect x="9" y="36" width="10" height="10"/>'
        '<rect x="23" y="36" width="10" height="10"/>'
        '<rect x="37" y="36" width="10" height="10"/>'
        '<path d="M28 20v8M14 36v-8h28v8M28 28v8"/>',
    ),
    "sso": (
        RED,
        '<circle cx="28" cy="20" r="7"/><path d="M14 44c1-9 7-14 14-14s13 5 14 14"/>',
    ),
    "billing": (
        GREEN,
        '<circle cx="28" cy="28" r="16"/>' + glyph_text(28, 35, 20, "$"),
    ),
    "external": (
        LINE,
        '<circle cx="28" cy="28" r="15"/>'
        '<ellipse cx="28" cy="28" rx="6" ry="15"/>'
        '<path d="M13 28h30M15 20h26M15 36h26"/>',
    ),
}

OUTLINES = {
    "role": (
        RED,
        '<path d="M10 38c0-12 8-20 18-20s18 8 18 20"/>'
        '<path d="M24 18v-4h8v4"/>'
        '<path d="M5 38h46c0 4-2 6-6 6H11c-4 0-6-2-6-6z"/>'
        '<path d="M22 20l-2 18M34 20l2 18"/>',
    ),
    "robot": (
        INK,
        '<rect x="8" y="16" width="40" height="28" rx="5"/>'
        '<circle cx="20" cy="30" r="4"/><circle cx="36" cy="30" r="4"/>'
        '<path d="M28 16V8"/><circle cx="28" cy="6" r="2" fill="#232F3E"/>'
        '<path d="M4 26v8M52 26v8"/>',
    ),
    "users": (
        INK,
        '<circle cx="22" cy="18" r="7"/>'
        '<path d="M8 46c1-10 6-16 14-16s13 6 14 16"/>'
        '<circle cx="38" cy="20" r="5"/><path d="M40 30c5 1 8 6 9 14"/>',
    ),
}

GITHUB_MARK = (
    "M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 "
    "0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13"
    "-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66"
    ".07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15"
    "-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 "
    "1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 "
    "1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 "
    "1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"
)

SPACELIFT = (
    '<path d="M28 10c7 5 9 13 7 22h-14c-2-9 0-17 7-22z"/>'
    '<circle cx="28" cy="22" r="3"/>'
    '<path d="M21 32l-5 6h7M35 32l5 6h-7M25 38l3 8 3-8"/>'
)


def glyph(kind, cx, cy):
    x, y = cx - S / 2, cy - S / 2
    if kind in TILES:
        color, body = TILES[kind]
        tile = el("rect", x=x, y=y, width=S, height=S, fill=color)
        return el("g", tile + stroke_group(x, y, "#fff", 2.4, body))
    if kind in OUTLINES:
        color, body = OUTLINES[kind]
        return stroke_group(x, y, color, 3, body)
    if kind == "aws":
        tile = el("rect", x=x, y=y, width=S, height=S, fill=INK)
        word = el(
            "text",
            "aws",
            x=cx,
            y=cy + 4,
            font_size=20,
            font_weight=700,
            fill="#fff",
            text_anchor="middle",
            font_family=FONT,
        )
        smile = el(
            "path",
            d=f"M{cx - 15} {cy + 11}q15 8 30 0",
            fill="none",
            stroke="#FF9900",
            stroke_width=3,
            stroke_linecap="round",
        )
        return el("g", tile + word + smile)
    if kind == "github":
        mark = el("path", fill=INK, d=GITHUB_MARK)
        return el("g", mark, transform=f"translate({cx - 26},{cy - 26}) scale(3.25)")
    if kind == "spacelift":
        disc = el("circle", cx=28, cy=28, r=27, fill=INK)
        rocket = stroke_group(0, 0, "#fff", 2.4, SPACELIFT)
        return el("g", disc + rocket, transform=f"translate({x},{y})")
    raise ValueError(kind)


def text(x, y, s, size=15, anchor="middle", fill=INK, weight=400, **extra):
    out.append(
        el(
            "text",
            s,
            x=x,
            y=y,
            font_size=size,
            text_anchor=anchor,
            fill=fill,
            font_weight=weight,
            **extra,
        )
    )


def node(kind, cx, cy, *lines):
    out.append(glyph(kind, cx, cy))
    for i, line in enumerate(lines):
        text(cx, cy + 48 + i * 18, line)


def path_d(points):
    return "M" + " L".join(f"{x},{y}" for x, y in points)


def line(points, **extra):
    out.append(
        el(
            "path",
            d=path_d(points),
            fill="none",
            stroke=LINE,
            stroke_width=1.8,
            **extra,
        )
    )


def arrow(points, label=None, at=None, anchor="middle"):
    line(points, marker_end="url(#arrow)")
    if label:
        text(*at, label, size=12.5, anchor=anchor, fill=MUTED, **HALO)


def header(x, y, color, icon, name, sub):
    out.append(el("rect", x=x, y=y, width=48, height=48, fill=color))
    out.append(stroke_group(x, y, "#fff", 2.2, icon))
    text(x + 58, y + 22, name, size=17, anchor="start", weight=600)
    text(x + 58, y + 40, sub, size=12, anchor="start", fill=MUTED)


def frame(x, y, w, h, color, width):
    out.append(
        el(
            "rect",
            x=x,
            y=y,
            width=w,
            height=h,
            fill="none",
            stroke=color,
            stroke_width=width,
        )
    )


ACCOUNT_ICON = (
    '<rect x="11" y="13" width="11" height="11"/><path d="M31 12l6 10h-12z"/>'
    '<circle cx="31" cy="31" r="5.5"/><path d="M11 37h11"/>'
)
CLOUD_ICON = '<path d="M15 33h-1a6 6 0 010-12 9 9 0 0117-3 7 7 0 014 15z"/>'


def account(x, y, w, h, name, sub):
    frame(x, y, w, h, PINK, 2.5)
    header(x, y, PINK, ACCOUNT_ICON, name, sub)


def build():
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="{FONT}">'
    )
    head = el("path", d="M0 0L10 5L0 10z", fill=LINE)
    marker = el(
        "marker",
        head,
        id="arrow",
        viewBox="0 0 10 10",
        refX=9,
        refY=5,
        markerWidth=7,
        markerHeight=7,
        orient="auto-start-reverse",
    )
    out.append(el("defs", marker))
    out.append(el("rect", width=W, height=H, fill="#fff"))

    org_y = 200
    frame(260, org_y, 1300, 1100, INK, 2)
    header(
        260,
        org_y,
        INK,
        CLOUD_ICON,
        "AWS Organization",
        "one OpenTofu root and Spacelift stack per workload",
    )

    top, bot = 270, 880
    ra, rb, rc = top + 140, top + 300, top + 460
    r1, r2 = bot + 140, bot + 300
    ext = 1680

    account(
        300,
        top,
        460,
        540,
        "production",
        "stacks: oconnordev-production, oconnordev-resume, drumrollworld",
    )
    account(820, top, 700, 540, "tools", "stack: oconnordev-tools")
    account(
        300,
        bot,
        460,
        380,
        "general",
        "management account, stack: oconnordev-general",
    )
    account(820, bot, 700, 380, "security", "stack: oconnordev-security")

    node("users", 130, ra, "Site visitors")
    node("robot", 130, rc, "Hermes agent", "+ MCP adapter")
    node("spacelift", 560, 80, "Spacelift")
    node("github", 1030, 80, "GitHub Actions")
    node("github", ext, ra, "GitHub, Spacelift", "MCP servers")
    node("external", ext, rb, "Microsoft Graph,", "Gmail, Google Calendar")
    node("external", ext, rc, "Thundermail, Schwab,", "Plaid APIs")
    node("aws", ext, r1, "AWS MCP Server")

    node("cloudfront", 400, ra, "CloudFront", "oconnor.dev, drumroll.world")
    node("s3", 620, ra, "S3", "site buckets")
    node("route53", 400, rb, "Route 53", "zones + DNSSEC")
    node("role", 620, rb, "Site deploy", "roles")
    node("cloudfront", 400, rc, "CloudFront", "mcp.oconnor.dev")

    node("role", 1030, rb, "GitHub OIDC", "broker roles")
    node("cognito", 1140, ra, "Cognito", "M2M tokens")
    node("gateway", 1140, rc, "AgentCore Gateway", "+ Cedar policies")
    node("identity", 1400, rb, "AgentCore Identity", "OAuth tokens")
    node("lambda", 1400, rc, "Lambda", "Thundermail, Schwab, Plaid")

    node("organizations", 400, r1, "Organizations", "+ SCPs")
    node("sso", 400, r2, "IAM Identity", "Center")
    node("billing", 620, r1, "Cost and usage", "export (S3)")
    node("cloudtrail", 620, r2, "Organization", "CloudTrail")

    node("athena", 1100, r1, "Athena", "cost analytics")
    node("gateway", 1260, r1, "Security AgentCore", "Gateway (IAM auth)")
    node("s3", 920, r2, "CloudTrail +", "Config buckets")
    node("config", 1100, r2, "Config", "aggregator")
    node("cloudwatch", 1260, r2, "CloudWatch logs", "sink (OAM)")

    arrow([(160, ra), (366, ra)])
    arrow([(430, ra), (586, ra)])
    arrow([(400, rb - 30), (400, ra + 74)])
    arrow([(620, rb - 30), (620, ra + 74)], "publish", (628, rb - 40), anchor="start")
    arrow([(160, rc), (366, rc)], "Cognito JWT", (205, rc - 10))
    arrow([(430, rc), (1106, rc)], "HTTPS origin", (600, rc - 10))

    arrow(
        [(560, 152), (560, org_y - 4)],
        "OpenTofu applies through a spacelift role in each account",
        (572, 182),
        anchor="start",
    )
    arrow([(1030, 152), (1030, rb - 34)], "OIDC", (1038, 236), anchor="start")
    arrow([(1000, rb), (654, rb)], "assume role", (880, rb - 10))

    arrow(
        [(1140, ra + 76), (1140, rc - 34)],
        "JWT authorizer",
        (1148, rb + 4),
        anchor="start",
    )
    line([(1170, rc), (1260, rc)])
    line([(1260, ra), (1260, rc)])
    arrow([(1260, ra), (ext - 34, ra)], "MCP targets", (1340, ra - 10))
    arrow([(1260, rb), (1366, rb)], "OpenAPI", (1313, rb - 10))
    arrow([(1430, rb), (ext - 34, rb)])
    arrow([(1260, rc), (1366, rc)], "Lambda", (1313, rc - 10))
    arrow([(1430, rc), (ext - 34, rc)])
    arrow(
        [(1260, rc), (1260, r1 - 34)],
        "aws target (SigV4)",
        (1268, bot - 30),
        anchor="start",
    )

    arrow([(1290, r1), (ext - 34, r1)])
    arrow([(1230, r1), (1134, r1)])
    arrow([(650, r1), (1066, r1)], "billing data", (860, r1 - 10))
    arrow([(650, r2), (886, r2)], "org trail", (705, r2 - 10))

    out.append("</svg>")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    OUT.write_text(build())
    print(OUT)
