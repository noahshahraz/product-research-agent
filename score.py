"""Scores the agent's raw candidates, writes the ranked report, posts to Discord.

Per-unit contribution margin:
    landed = unit_cost + freight_per_unit + unit_cost * duty_rate
    fees   = price * platform_fee_rate + fulfill_fee
    CAC    = est_cpc / est_cvr
    margin = orders * (price - landed - fees) - CAC   (per customer, 12 months)
"""

import json
import math
import os
import sys
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"

PRICE_RANGE = (40.0, 200.0)
MIN_MARGIN_PCT = 0.25

# Weights must sum to 1. Tune these once you have real test results.
WEIGHTS = {
    "margin": 0.35,
    "trend": 0.20,
    "demand": 0.15,
    "competition": 0.15,
    "complaints": 0.15,
}


def economics(c: dict) -> dict:
    """Margin per customer over 12 months. Ads are paid once; reorders are not."""
    orders = max(1.0, float(c.get("expected_orders_per_customer", 1)))
    landed = c["unit_cost"] + c["freight_per_unit"] + c["unit_cost"] * c["duty_rate"]
    fees = c["price"] * c["platform_fee_rate"] + c["fulfill_fee"]
    cac = c["est_cpc"] / c["est_cvr"] if c["est_cvr"] > 0 else math.inf
    revenue = orders * c["price"]
    margin = orders * (c["price"] - landed - fees) - cac
    margin_pct = margin / revenue if revenue > 0 else -math.inf
    return {
        "orders_per_customer": orders,
        "landed_cost": round(landed, 2),
        "fees": round(fees, 2),
        "cac": round(cac, 2) if math.isfinite(cac) else None,
        "margin": round(margin, 2) if math.isfinite(margin) else None,
        "margin_pct": margin_pct,
    }


def score(c: dict, econ: dict) -> float:
    margin_component = max(0.0, min(econ["margin_pct"] / 0.5, 1.0)) * 10
    return (
        WEIGHTS["margin"] * margin_component
        + WEIGHTS["trend"] * c["trend_score"]
        + WEIGHTS["demand"] * c["demand_score"]
        + WEIGHTS["competition"] * c["competition_score"]
        + WEIGHTS["complaints"] * c["complaint_score"]
    )


def evaluate(raw: dict) -> tuple[list, list]:
    ranked, killed = [], []
    for c in raw["candidates"]:
        if c.get("kill_reason"):
            killed.append({"name": c["name"], "reason": c["kill_reason"]})
            continue
        econ = economics(c)
        lo, hi = PRICE_RANGE
        if not lo <= c["price"] <= hi:
            killed.append({"name": c["name"], "reason": f"price ${c['price']:.0f} outside range"})
            continue
        if econ["margin_pct"] < MIN_MARGIN_PCT:
            pct = econ["margin_pct"]
            shown = f"{pct:.0%}" if math.isfinite(pct) else "n/a"
            killed.append({"name": c["name"], "reason": f"margin after ads {shown} is under {MIN_MARGIN_PCT:.0%}"})
            continue
        ranked.append({**c, **econ, "score": round(score(c, econ), 2)})
    ranked.sort(key=lambda r: r["score"], reverse=True)
    return ranked, killed


def markdown_report(raw: dict, ranked: list, killed: list) -> str:
    lines = [
        f"# Product research: {raw['run_date']}",
        "",
        raw.get("summary", ""),
        "",
        f"Changes since last run: {raw.get('changes_vs_last_run', 'n/a')}",
        "",
        "## Ranked shortlist",
        "",
        "Margin is per customer over 12 months, after one round of ad spend.",
        "",
        "| # | Product | Price | Landed | CAC | Orders/customer | Margin | Margin % | Score |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(ranked[:10], 1):
        lines.append(
            f"| {i} | {r['name']} | ${r['price']:.0f} | ${r['landed_cost']:.2f} | "
            f"${r['cac']:.2f} | {r['orders_per_customer']:.1f} | ${r['margin']:.2f} | "
            f"{r['margin_pct']:.0%} | {r['score']:.1f} |"
        )
    lines += ["", "## Details", ""]
    for r in ranked[:10]:
        lines += [
            f"### {r['name']}",
            f"- Angle: {r.get('angle', '')}",
            f"- Fixable complaints: {', '.join(r.get('fixable_complaints', [])) or 'none found'}",
            f"- Requirements to sell: {r.get('regulatory_notes', 'not checked')}",
            f"- Notes: {r.get('notes', '')}",
            f"- Sources: {' '.join(r.get('sources', []))}",
            "",
        ]
    lines += ["## Killed", ""]
    lines += [f"- {k['name']}: {k['reason']}" for k in killed]
    return "\n".join(lines) + "\n"


def post_to_discord(raw: dict, ranked: list, killed: list) -> None:
    url = os.getenv("DISCORD_WEBHOOK_URL")
    if not url:
        print("DISCORD_WEBHOOK_URL not set, skipping Discord post.")
        return
    lines = [f"**Product research {raw['run_date']}**", raw.get("summary", "")[:500], ""]
    for i, r in enumerate(ranked[:5], 1):
        lines.append(
            f"{i}. {r['name']}: ${r['price']:.0f}, margin {r['margin_pct']:.0%} after ads, score {r['score']:.1f}"
        )
    lines.append(f"\n{len(ranked)} passed, {len(killed)} killed.")
    server, repo = os.getenv("GITHUB_SERVER_URL"), os.getenv("GITHUB_REPOSITORY")
    if server and repo:
        lines.append(f"Full report: {server}/{repo}/blob/main/results/{raw['run_date']}.md")
    content = "\n".join(lines)[:1990]
    resp = requests.post(url, json={"content": content}, timeout=30)
    resp.raise_for_status()
    print("Posted to Discord.")


def main() -> int:
    run_date = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    raw_path = RESULTS / f"{run_date}.raw.json"
    if not raw_path.exists():
        print(f"Missing {raw_path}. Run agent.py first.", file=sys.stderr)
        return 1
    raw = json.loads(raw_path.read_text())
    raw.setdefault("run_date", run_date)

    ranked, killed = evaluate(raw)
    (RESULTS / f"{run_date}.json").write_text(
        json.dumps({"run_date": raw["run_date"], "ranked": ranked, "killed": killed}, indent=2)
    )
    (RESULTS / f"{run_date}.md").write_text(markdown_report(raw, ranked, killed))
    print(f"{len(ranked)} ranked, {len(killed)} killed. Report: results/{run_date}.md")
    post_to_discord(raw, ranked, killed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
