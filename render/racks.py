"""Render assets/racks-{light,dark}.svg and the upstream table in README.md.

Device LEDs and table rows come from the live state of the pull requests in
racks.yaml, so the diagram and the table always agree.
"""

import os
import sys

import yaml

from common import LOGIN, ROOT, THEMES, Fonts, graphql, write_svg

TABLE_HEADING = "## Open source contributions to Kubernetes, KubeVirt, Talos Linux and Ceph"

SIZES = {
    "dev": ("sans-med", 13.5, 0),
    "sub": ("sans", 12, 0),
    "host": ("mono-med", 12, 0),
    "spine": ("mono-med", 13.5, 0),
    "cnt": ("mono-med", 12, 0),
    "cap": ("sans-med", 12.5, 0),
    "plate": ("sans", 12.5, 0),
    "small": ("sans", 12, 0),
    "legend": ("sans", 12.5, 0),
}

W = 960
MARGIN = 20
RACK_W = 296
RACK_GAP = (W - 2 * MARGIN - 3 * RACK_W) / 2
CENTRAL_Y = 34
CENTRAL_H = 62
CENTRAL_X0 = 190
CENTRAL_X1 = W - 170
SPINE_Y = 150
SPINE_H = 40
SPINE_W = 220
RACK_TOP = 266
RAIL = 12
LEAF_H = 30
LEAF_PORTS = 7
DEV_H = 38
DEV_GAP = 4
PLATE_H = 26
INNER_W = RACK_W - 2 * (RAIL + 4)
LEAF_W = (INNER_W - DEV_GAP) / 2
SPINES = [W / 2 - SPINE_W / 2 - 150, W / 2 - SPINE_W / 2 + 150]
# One spine-leaf link fails for 4s every 24s; ECMP keeps the leaf on the other spine.
FAILING_LINK = (0, 2)


def load_config():
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "racks.yaml")) as fh:
        return yaml.safe_load(fh)


def pr_states(urls):
    states = {}
    urls = sorted(set(urls))
    for start in range(0, len(urls), 50):
        chunk = urls[start:start + 50]
        fields = "".join(
            f'p{i}: resource(url: "{url}") {{ ... on PullRequest {{ state }} }} ' for i, url in enumerate(chunk)
        )
        data = graphql(f"query {{ {fields} }}")
        for i, url in enumerate(chunk):
            node = data[f"p{i}"]
            if node is None:
                raise RuntimeError(f"{url} not found")
            states[url] = node["state"]
    return states


def upstream_prs():
    query = """
    query($q: String!, $after: String) {
      search(query: $q, type: ISSUE, first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes { ... on PullRequest { url state title } }
      }
    }"""
    prs = []
    after = None
    while True:
        data = graphql(query, {"q": f"author:{LOGIN} is:pr -user:{LOGIN} is:public", "after": after})["search"]
        prs += [n for n in data["nodes"] if n]
        if not data["pageInfo"]["hasNextPage"]:
            return prs
        after = data["pageInfo"]["endCursor"]


def pr_urls(racks):
    return [pr["url"] for r in racks for d in r["devices"] for pr in d.get("prs", [])]


def device_leds(device, states):
    merged = sum(states[pr["url"]] == "MERGED" for pr in device.get("prs", []))
    opened = sum(states[pr["url"]] == "OPEN" for pr in device.get("prs", [])) + len(device.get("posted", []))
    leds = []
    if merged:
        leds.append(("merged", merged))
    if opened:
        leds.append(("open", opened))
    if device.get("maintains"):
        leds.append(("own", None))
    return leds


def rack_x(i):
    return MARGIN + i * (RACK_W + RACK_GAP)


def spine_port(sx, p):
    return sx + SPINE_W - 14 - (12 - p) * 9


def leaf_port(lx, p):
    return lx + LEAF_W - 10 - (LEAF_PORTS - p) * 7.5


def build_svg(theme, fonts, racks, states):
    c = THEMES[theme]
    slots = max(len(r["devices"]) for r in racks)
    rack_h = LEAF_H + DEV_GAP + slots * (DEV_H + DEV_GAP) + PLATE_H + 20
    height = RACK_TOP + rack_h + 110
    out = []
    overflow = []

    def text(style, s, x, y, cls, anchor="start"):
        frag, width = fonts.text(style, s, x, y, cls, anchor)
        out.append(frag)
        return width

    # Central plane: the only place that accepts pushes. Racks pull from it.
    cw = text("cap", "Central plane", MARGIN, 20, "ink")
    text("small", "builds, signs and publishes. Racks pull, never push.", MARGIN + cw + 10, 20, "muted")
    out.append(f'<rect x="{CENTRAL_X0 + .5}" y="{CENTRAL_Y + .5}" width="{CENTRAL_X1 - CENTRAL_X0 - 1}" height="{CENTRAL_H - 1}" rx="4" fill="none" stroke="{c["line"]}" stroke-width="1.5"/>')
    items = [("Git", "GitLab"), ("CI/CD", "GitLab CI  Tekton"), ("OCI registry", "Harbor  Cosign"), ("Identity", "Keycloak  SSO  MFA")]
    item_w = (CENTRAL_X1 - CENTRAL_X0 - 20 - 8 * (len(items) - 1)) / len(items)
    for n, (name, sub) in enumerate(items):
        bx = CENTRAL_X0 + 10 + n * (item_w + 8)
        out.append(f'<rect x="{bx + .5}" y="{CENTRAL_Y + 10.5}" width="{item_w - 1}" height="{CENTRAL_H - 21}" rx="2" fill="{c["cell"]}" stroke="{c["line"]}"/>')
        text("dev", name, bx + 10, CENTRAL_Y + 27, "ink")
        if text("sub", sub, bx + 10, CENTRAL_Y + 43, "muted") > item_w - 16:
            overflow.append(f"central {name}")
    ay = CENTRAL_Y + CENTRAL_H / 2
    text("cap", "Engineers", MARGIN, ay - 2, "ink")
    if text("small", "SSO, MFA, zero trust", MARGIN, ay + 15, "muted") > CENTRAL_X0 - MARGIN - 44:
        overflow.append("engineers caption")
    ax0, ax1 = CENTRAL_X0 - 36, CENTRAL_X0 - 4
    out.append(f'<line x1="{ax0}" y1="{ay}" x2="{ax1 - 5}" y2="{ay}" stroke="{c["muted"]}" stroke-width="1.5"/>')
    out.append(f'<path d="M{ax1 - 6},{ay - 4} L{ax1},{ay} L{ax1 - 6},{ay + 4} Z" fill="{c["muted"]}"/>')
    text("small", "push", (ax0 + ax1) / 2, ay - 7, "faint", "middle")
    text("small", "Signed artifacts", W - MARGIN, ay - 2, "muted", "end")
    text("small", "flow down only", W - MARGIN, ay + 15, "muted", "end")

    # Pull-only links from the central plane into the fabric; packets only move down.
    for k, sx in enumerate(SPINES):
        px = sx + SPINE_W / 2
        y0, y1 = CENTRAL_Y + CENTRAL_H, SPINE_Y
        out.append(f'<line x1="{px}" y1="{y0}" x2="{px}" y2="{y1}" stroke="{c["link"]}" stroke-dasharray="4 3"/>')
        for j in range(2):
            out.append(
                f'<circle class="pkt" r="2.2" opacity=".75" fill="{c["muted"]}">'
                f'<animateMotion dur="2.4s" begin="-{(j * 1.2 + k * 0.6):.1f}s" repeatCount="indefinite" path="M{px},{y0} L{px},{y1}"/></circle>'
            )
    text("small", "pull only", W / 2, (CENTRAL_Y + CENTRAL_H + SPINE_Y) / 2 + 4, "faint", "middle")

    fy = SPINE_Y + 14
    text("cap", "Fabric", MARGIN, fy, "ink")
    for n, line in enumerate(("leaf-spine, eBGP unnumbered", "EVPN-VXLAN, ECMP")):
        if text("small", line, MARGIN, fy + 17 + n * 16, "muted") > SPINES[0] - MARGIN - 12:
            overflow.append("fabric caption")
    for n, line in enumerate(("Racks show roles,", "not failure domains")):
        text("small", line, W - MARGIN, fy + n * 16, "faint", "end")

    leaf_xs = []
    for i in range(3):
        ix = rack_x(i) + RAIL + 4
        leaf_xs += [ix, ix + LEAF_W + DEV_GAP]

    links = []
    for s_i, sx in enumerate(SPINES):
        for l_i, lx in enumerate(leaf_xs):
            x1, y1 = spine_port(sx, l_i) + 3, SPINE_Y + SPINE_H
            x2, y2 = leaf_port(lx, LEAF_PORTS - 2 + s_i) + 2.5, RACK_TOP + 8
            links.append(((s_i, l_i), x1, y1, x2, y2))
            out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{c["link"]}"/>')
    for n, sx in enumerate(SPINES, 1):
        out.append(f'<rect x="{sx + .5}" y="{SPINE_Y + .5}" width="{SPINE_W - 1}" height="{SPINE_H - 1}" rx="3" fill="{c["cell"]}" stroke="{c["line"]}"/>')
        text("spine", f"spine-{n}", sx + 14, SPINE_Y + 25, "ink")
        for p in range(12):
            fill = c["led"] if p < len(leaf_xs) else c["line"]
            out.append(f'<rect x="{spine_port(sx, p)}" y="{SPINE_Y + 17}" width="6" height="5" fill="{fill}"/>')

    timing = 'dur="24s" repeatCount="indefinite" keyTimes="0;.80;.81;.97;1"'
    for key, x1, y1, x2, y2 in links:
        failing = key == FAILING_LINK
        k = key[0] * len(leaf_xs) + key[1]
        for direction, (a, b) in enumerate((((x1, y1), (x2, y2)), ((x2, y2), (x1, y1)))):
            dur = 3.2 + (k % 3) * 0.7
            begin = (k * 0.55 + direction * 1.6) % dur
            fade = f'<animate attributeName="opacity" values=".75;.75;0;0;.75" {timing}/>' if failing else ""
            # Negative begin puts each packet mid-link on the first frame.
            out.append(
                f'<circle class="pkt" r="2.2" opacity=".75" fill="{c["muted"]}">'
                f'<animateMotion dur="{dur:.1f}s" begin="-{begin:.2f}s" repeatCount="indefinite" path="M{a[0]},{a[1]} L{b[0]},{b[1]}"/>'
                f"{fade}</circle>"
            )
        if failing:
            show = f'<animate attributeName="opacity" values="0;0;1;1;0" {timing}/>'
            out.append(f'<line class="pkt" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{c["sec"]}" stroke-width="1.5" stroke-dasharray="3 3" opacity="0">{show}</line>')
            sp = spine_port(SPINES[key[0]], key[1])
            out.append(f'<rect class="pkt" x="{sp}" y="{SPINE_Y + 17}" width="6" height="5" fill="{c["sec"]}" opacity="0">{show}</rect>')
            lp = leaf_port(leaf_xs[key[1]], LEAF_PORTS - 2 + key[0])
            out.append(f'<rect class="pkt" x="{lp}" y="{RACK_TOP + 20}" width="5" height="5" fill="{c["sec"]}" opacity="0">{show}</rect>')

    for i, rack in enumerate(racks):
        x = rack_x(i)
        y = RACK_TOP
        devices = rack["devices"]
        out.append(f'<rect x="{x + .5}" y="{y + .5}" width="{RACK_W - 1}" height="{rack_h - 1}" rx="4" fill="none" stroke="{c["line"]}" stroke-width="1.5"/>')
        for rx in (x + 6, x + RACK_W - 6):
            out.append(f'<line x1="{rx}" y1="{y + 8}" x2="{rx}" y2="{y + rack_h - 8}" stroke="{c["faint"]}" stroke-dasharray="1 5" stroke-linecap="round"/>')
        ix = x + RAIL + 4
        cy = y + 8

        # Two top-of-rack leaves; every host is dual-homed.
        for n in (1, 2):
            lx = leaf_xs[i * 2 + n - 1]
            out.append(f'<rect x="{lx + .5}" y="{cy + .5}" width="{LEAF_W - 1}" height="{LEAF_H - 1}" rx="2" fill="{c["cell"]}" stroke="{c["line"]}"/>')
            text("host", f"leaf-{rack['id'].lower()}{n}", lx + 10, cy + 19.5, "ink")
            for p in range(LEAF_PORTS):
                if p >= LEAF_PORTS - 2:
                    port = f'fill="{c["led"]}"'
                elif p < len(devices):
                    port = f'fill="{c["led"]}" opacity=".45"'
                else:
                    port = f'fill="{c["line"]}"'
                out.append(f'<rect x="{leaf_port(lx, p)}" y="{cy + 12}" width="5" height="5" {port}/>')
        cy += LEAF_H + DEV_GAP

        for slot in range(slots):
            if slot >= len(devices):
                out.append(f'<rect x="{ix + .5}" y="{cy + .5}" width="{INNER_W - 1}" height="{DEV_H - 1}" rx="2" fill="{c["blank"]}" stroke="{c["line"]}" stroke-dasharray="2 3"/>')
                cy += DEV_H + DEV_GAP
                continue
            device = devices[slot]
            out.append(f'<rect x="{ix + .5}" y="{cy + .5}" width="{INNER_W - 1}" height="{DEV_H - 1}" rx="2" fill="{c["cell"]}" stroke="{c["line"]}"/>')
            if device.get("security"):
                out.append(f'<rect x="{ix + 1}" y="{cy + 1}" width="3" height="{DEV_H - 2}" fill="{c["sec"]}"/>')
            name_w = text("dev", device["name"], ix + 12, cy + 16, "ink")
            tools_w = text("sub", device["tools"], ix + 12, cy + 31.5, "muted")

            lx = ix + INNER_W - 12
            if device.get("pull"):
                lx -= text("cnt", "pull", lx, cy + 15.5, "muted", "end") + 6
                out.append(f'<line x1="{lx - 3.5}" y1="{cy + 6}" x2="{lx - 3.5}" y2="{cy + 13}" stroke="{c["muted"]}" stroke-width="1.5"/>')
                out.append(f'<path d="M{lx - 7.5},{cy + 11} L{lx - 3.5},{cy + 16} L{lx + .5},{cy + 11} Z" fill="{c["muted"]}"/>')
                lx -= 7 + 10
            for kind, count in reversed(device_leds(device, states)):
                if count is not None:
                    lx -= text("cnt", str(count), lx, cy + 15.5, "ink", "end") + 5
                if kind == "open":
                    out.append(f'<rect x="{lx - 6.5}" y="{cy + 8.5}" width="6" height="6" fill="none" stroke="{c["led"]}"/>')
                else:
                    out.append(f'<rect x="{lx - 7}" y="{cy + 8}" width="7" height="7" fill="{c["led" if kind == "merged" else "own"]}"/>')
                lx -= 7 + 10
            if ix + 12 + name_w + 12 > lx + 10 or ix + 12 + tools_w > ix + INNER_W - 10:
                overflow.append(device["name"])
            cy += DEV_H + DEV_GAP

        py = y + rack_h - 8 - PLATE_H
        out.append(f'<line x1="{ix}" y1="{py - 1}" x2="{ix + INNER_W}" y2="{py - 1}" stroke="{c["line"]}"/>')
        pw = text("cap", f"Rack {rack['id']}", ix + 2, py + 18, "ink")
        text("plate", rack["role"], ix + 2 + pw + 8, py + 18, "muted")

    oy = RACK_TOP + rack_h + 18
    centers = [rack_x(i) + RACK_W / 2 for i in range(3)]
    out.append(f'<line x1="{centers[0]}" y1="{oy}" x2="{centers[-1]}" y2="{oy}" stroke="{c["faint"]}" stroke-dasharray="4 4"/>')
    for bx in centers:
        out.append(f'<line x1="{bx}" y1="{RACK_TOP + rack_h}" x2="{bx}" y2="{oy}" stroke="{c["faint"]}" stroke-dasharray="4 4"/>')
    ow = text("cap", "Out of band", MARGIN, oy + 26, "ink")
    text("small", "BMC, Redfish, IPMI, serial console", MARGIN + ow + 10, oy + 26, "muted")

    ly = oy + 58
    lx = MARGIN
    for kind, label in (("merged", "Merged upstream"), ("open", "In review"), ("own", "Maintainer"), ("sec", "Security work")):
        if kind == "open":
            out.append(f'<rect x="{lx + .5}" y="{ly - 7.5}" width="6" height="6" fill="none" stroke="{c["led"]}"/>')
        elif kind == "sec":
            out.append(f'<rect x="{lx + 2}" y="{ly - 10}" width="3" height="11" fill="{c["sec"]}"/>')
        else:
            out.append(f'<rect x="{lx}" y="{ly - 8}" width="7" height="7" fill="{c["led" if kind == "merged" else "own"]}"/>')
        lx += 14 + text("legend", label, lx + 14, ly, "muted") + 28
    text("legend", "Built for KRITIS, NIS2, ISO 27001 and BSI IT-Grundschutz", W - MARGIN, ly, "muted", "end")

    style = (
        f".ink{{fill:{c['ink']}}}.muted{{fill:{c['muted']}}}.faint{{fill:{c['faint']}}}"
        "@media (prefers-reduced-motion:reduce){.pkt{display:none}}"
    )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {height:.0f}" width="{W}" height="{height:.0f}" role="img" aria-labelledby="t d">'
        '<title id="t">Private cloud with a central plane and three racks: control plane, compute, storage</title>'
        '<desc id="d">A central plane with GitLab, CI/CD, a Harbor OCI registry and Keycloak accepts pushes from engineers through SSO and zero trust access. '
        "Racks pull from it, never push, and keep a local Git mirror and Harbor replica. A leaf-spine BGP fabric connects three racks. Control plane rack with Kubernetes, Cluster API, Metal3, Ironic, "
        "Argo CD, Flux, Kyverno, Sigstore, Vault, Keycloak, SPIFFE and OpenTelemetry. Compute rack with GPU nodes for vLLM and llm-d, KubeVirt, Firecracker, confidential VMs and containers with AMD SEV-SNP and Intel TDX, kubelet, "
        "OVN-Kubernetes, Cilium, Multus, Istio, Envoy, HAProxy, LoxiLB, BGP to the host with BIRD, Talos Linux and the Linux kernel with eBPF and IPsec. "
        "Storage rack with Ceph, Rook, CloudNativePG, Kafka, NATS, LINSTOR and Velero. Markers show upstream pull requests per component.</desc>"
        f"<style>{style}</style><defs>{fonts.defs_svg()}</defs>" + "".join(out) + "</svg>\n"
    )
    return svg, overflow


def table_markdown(racks, states):
    rows = []
    for rack in racks:
        first = True
        for device in rack["devices"]:
            entries = [(pr, "merged" if states[pr["url"]] == "MERGED" else "in review")
                       for pr in device.get("prs", []) if states[pr["url"]] != "CLOSED"]
            entries += [(post, f"posted to {post['where']}") for post in device.get("posted", [])]
            for entry, state in entries:
                label = f"**{rack['id']}** {rack['role']}" if first else ""
                first = False
                change = entry["change"].replace("{url}", entry["url"])
                rows.append(f"| {label} | {device['name']} | {change} | <kbd>{state}</kbd> |")
    return "\n".join([
        TABLE_HEADING,
        "",
        "The diagram is the platform I build. Each marker in it is a pull request in this table.",
        "",
        "| Rack | Component | What changed | State |",
        "| :-- | :-- | :-- | :-- |",
        *rows,
        "",
        "",
    ])


def update_readme(table):
    path = os.path.join(ROOT, "README.md")
    with open(path) as fh:
        readme = fh.read()
    start = readme.index(TABLE_HEADING)
    end = readme.index("\n## ", start + len(TABLE_HEADING)) + 1
    with open(path, "w") as fh:
        fh.write(readme[:start] + table + readme[end:])


def report_unmapped(racks, ignored):
    mapped = set(pr_urls(racks)) | set(ignored)
    lines = [f"- {pr['state'].lower()} {pr['url']} {pr['title']}" for pr in upstream_prs()
             if pr["url"] not in mapped and pr["state"] != "CLOSED"]
    if not lines:
        return
    message = "Upstream pull requests not placed in racks.yaml:\n" + "\n".join(lines) + "\n"
    print(message)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write(message)


def main():
    config = load_config()
    racks = config["racks"]
    states = pr_states(pr_urls(racks))
    for theme in THEMES:
        svg, overflow = build_svg(theme, Fonts(SIZES), racks, states)
        if overflow:
            sys.exit(f"text overflows its device: {', '.join(overflow)}")
        print(write_svg("racks", theme, svg))
    update_readme(table_markdown(racks, states))
    report_unmapped(racks, config.get("ignored", []))


if __name__ == "__main__":
    main()
