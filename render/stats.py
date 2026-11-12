"""Render assets/stats-{light,dark}.svg from the GitHub API.

Languages are weighted by contributions in the last year, across all public
repositories, upstream included. The usual cards count bytes in owned repos only.
Each repository counts log2(1 + contributions), so one busy repository with
automated commits cannot outweigh a year of upstream work.
"""

import datetime
import math
import os
import re

from common import LOGIN, ROOT, THEMES, Fonts, graphql, write_svg

SIZES = {
    "title": ("sans-med", 13.5, 0),
    "num": ("mono-med", 26, 0),
    "label": ("sans", 12, 0),
    "lang": ("sans", 12.5, 0),
    "pct": ("mono", 12, 0),
    "axis": ("mono", 10.5, 0),
}

W = 960
H = 214
TOP = 8
CARD_H = H - 2 * TOP
GAP = 20
CARDS = [(0, 310), (330, 280), (630, 330)]
PAD = 20
# Markup and build files say little about what someone writes.
SKIP_LANGUAGES = {"HTML", "CSS", "SCSS", "Makefile", "Dockerfile", "Mustache", "Jinja", "Smarty", "Roff", "Batchfile"}
TOP_LANGUAGES = 6


def collect():
    data = graphql(
        """
        query($login: String!) {
          user(login: $login) {
            contributionsCollection {
              contributionCalendar {
                totalContributions
                weeks { contributionDays { contributionCount date } }
              }
              commitContributionsByRepository(maxRepositories: 100) {
                contributions { totalCount }
                repository { isPrivate languages(first: 8, orderBy: {field: SIZE, direction: DESC}) { edges { size node { name color } } } }
              }
              pullRequestContributionsByRepository(maxRepositories: 100) {
                contributions { totalCount }
                repository { isPrivate languages(first: 8, orderBy: {field: SIZE, direction: DESC}) { edges { size node { name color } } } }
              }
            }
            repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC, first: 100) {
              nodes { stargazerCount }
            }
          }
          merged: search(query: $merged, type: ISSUE, first: 100) {
            issueCount
            nodes { ... on PullRequest { repository { nameWithOwner } } }
          }
        }
        """.replace("$merged", '"author:' + LOGIN + ' is:pr is:merged is:public -user:' + LOGIN + '"'),
        {"login": LOGIN},
    )
    user = data["user"]
    cc = user["contributionsCollection"]

    weights = {}
    colors = {}
    for entry in cc["commitContributionsByRepository"] + cc["pullRequestContributionsByRepository"]:
        repo = entry["repository"]
        edges = [e for e in repo["languages"]["edges"] if e["node"]["name"] not in SKIP_LANGUAGES]
        total = sum(e["size"] for e in edges)
        if repo["isPrivate"] or not total:
            continue
        for e in edges:
            name = e["node"]["name"]
            weights[name] = weights.get(name, 0) + math.log2(1 + entry["contributions"]["totalCount"]) * e["size"] / total
            colors[name] = e["node"]["color"] or "#8b949e"
    ranked = sorted(weights.items(), key=lambda kv: -kv[1])
    total_weight = sum(weights.values()) or 1
    languages = [(name, w / total_weight, colors[name]) for name, w in ranked[:TOP_LANGUAGES]]
    other = 1 - sum(share for _, share, _ in languages)
    if other > 0.005:
        languages.append(("Other", other, None))

    weeks = [sum(d["contributionCount"] for d in w["contributionDays"]) for w in cc["contributionCalendar"]["weeks"]]
    first_days = [w["contributionDays"][0]["date"] for w in cc["contributionCalendar"]["weeks"]]
    return {
        "contributions": cc["contributionCalendar"]["totalContributions"],
        "merged": data["merged"]["issueCount"],
        "projects": len({n["repository"]["nameWithOwner"] for n in data["merged"]["nodes"] if n}),
        "stars": sum(n["stargazerCount"] for n in user["repositories"]["nodes"]),
        "languages": languages,
        "weeks": weeks,
        "week_starts": first_days,
    }


def build_svg(theme, fonts, stats):
    c = THEMES[theme]
    out = []

    def text(style, s, x, y, cls, anchor="start"):
        frag, width = fonts.text(style, s, x, y, cls, anchor)
        out.append(frag)
        return width

    for x, w in CARDS:
        out.append(f'<rect x="{x + .5}" y="{TOP + .5}" width="{w - 1}" height="{CARD_H - 1}" rx="4" fill="{c["cell"]}" stroke="{c["line"]}"/>')

    # Card 1: four numbers in a 2x2 grid.
    x0, w0 = CARDS[0]
    text("title", "Open source", x0 + PAD, TOP + 30, "ink")
    cells = [
        (f"{stats['merged']}", "merged upstream"),
        (f"{stats['projects']}", "upstream projects"),
        (f"{stats['contributions']:,}", "contributions, 1 year"),
        (f"{stats['stars']}", "stars on own repos"),
    ]
    col_w = (w0 - 2 * PAD) / 2
    for i, (num, label) in enumerate(cells):
        cx = x0 + PAD + (i % 2) * col_w
        cy = TOP + 82 + (i // 2) * 64
        text("num", num, cx, cy, "ink")
        if text("label", label, cx, cy + 20, "muted") > col_w - 12:
            raise SystemExit(f"stats label too wide: {label}")

    # Card 2: languages as one stacked bar plus a list.
    x1, w1 = CARDS[1]
    text("title", "Languages, by contribution", x1 + PAD, TOP + 30, "ink")
    bar_w = w1 - 2 * PAD
    bx = x1 + PAD
    for name, share, color in stats["languages"]:
        seg = bar_w * share
        out.append(f'<rect x="{bx:.2f}" y="{TOP + 46}" width="{max(seg - 1.5, 0.5):.2f}" height="8" fill="{color or c["line"]}"/>')
        bx += seg
    for i, (name, share, color) in enumerate(stats["languages"]):
        col, row = i % 2, i // 2
        lx = x1 + PAD + col * bar_w / 2
        ly = TOP + 86 + row * 26
        out.append(f'<rect x="{lx}" y="{ly - 9}" width="8" height="8" rx="4" fill="{color or c["line"]}"/>')
        text("lang", name, lx + 14, ly, "ink")
        text("pct", f"{share * 100:.0f}%", lx + bar_w / 2 - 16, ly, "muted", "end")

    # Card 3: contributions per week over the last year.
    x2, w2 = CARDS[2]
    text("title", "Contributions per week", x2 + PAD, TOP + 30, "ink")
    weeks = stats["weeks"]
    peak = max(weeks) or 1
    chart_x = x2 + PAD
    chart_w = w2 - 2 * PAD
    chart_top = TOP + 50
    chart_bottom = TOP + CARD_H - 34
    step = chart_w / len(weeks)
    out.append(f'<line x1="{chart_x}" y1="{chart_bottom + .5}" x2="{chart_x + chart_w}" y2="{chart_bottom + .5}" stroke="{c["line"]}"/>')
    for i, count in enumerate(weeks):
        h = (chart_bottom - chart_top) * count / peak
        if count:
            out.append(f'<rect x="{chart_x + i * step + .75:.2f}" y="{chart_bottom - h:.2f}" width="{step - 1.5:.2f}" height="{h:.2f}" rx="1" fill="{c["led"]}"/>')
    text("axis", f"peak {peak}", x2 + w2 - PAD, TOP + 30, "muted", "end")
    last_month = None
    for i, day in enumerate(stats["week_starts"]):
        month = datetime.date.fromisoformat(day).strftime("%b")
        if month != last_month and i < len(weeks) - 3:
            if last_month is not None and month in ("Jan", "Apr", "Jul", "Oct"):
                text("axis", month, chart_x + i * step, chart_bottom + 18, "faint")
            last_month = month

    style = f".ink{{fill:{c['ink']}}}.muted{{fill:{c['muted']}}}.faint{{fill:{c['faint']}}}"
    langs = ", ".join(f"{n} {s * 100:.0f}%" for n, s, _ in stats["languages"])
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-labelledby="t d">'
        "<title id=\"t\">GitHub activity of Usman Malik</title>"
        f'<desc id="d">{stats["merged"]} pull requests merged in {stats["projects"]} upstream projects. '
        f'{stats["contributions"]} contributions in the last year. Languages by contribution: {langs}.</desc>'
        f"<style>{style}</style><defs>{fonts.defs_svg()}</defs>" + "".join(out) + "</svg>\n"
    )
    return svg


def update_readme(stats):
    """Put the numbers in the image alt text, because crawlers do not read SVG images."""
    path = os.path.join(ROOT, "README.md")
    with open(path) as fh:
        readme = fh.read()
    top = ", ".join(f"{name} {share * 100:.0f}%" for name, share, _ in stats["languages"][:3])
    alt = (
        f"GitHub activity of Usman Malik. {stats['merged']} pull requests merged in {stats['projects']} upstream projects "
        f"and {stats['contributions']:,} contributions in the last year. Top languages by contribution are {top}."
    )
    readme, count = re.subn(r'<img alt="GitHub activity of Usman Malik[^"]*" src="assets/stats-light.svg">',
                            f'<img alt="{alt}" src="assets/stats-light.svg">', readme)
    if count != 1:
        raise SystemExit("README.md has no stats image to update")
    with open(path, "w") as fh:
        fh.write(readme)


def main():
    stats = collect()
    update_readme(stats)
    for theme in THEMES:
        print(write_svg("stats", theme, build_svg(theme, Fonts(SIZES), stats)))


if __name__ == "__main__":
    main()
