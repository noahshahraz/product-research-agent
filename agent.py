"""Runs the product research agent and writes results/<date>.raw.json.

The agent only gathers evidence and raw inputs. All margin math and ranking
happens in score.py, so the numbers stay deterministic and auditable.
"""

import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
PROMPT_FILE = ROOT / "prompts" / "research.md"

MODEL = os.getenv("AGENT_MODEL", "claude-sonnet-5-5")
MAX_TURNS = int(os.getenv("AGENT_MAX_TURNS", "80"))


def previous_ranking(today: str) -> str:
    """Short summary of the last scored run, so the agent can report changes."""
    scored = sorted(
        p for p in RESULTS.glob("*.json")
        if not p.name.endswith(".raw.json") and p.stem != today
    )
    if not scored:
        return "No previous run. This is the first run."
    last = json.loads(scored[-1].read_text())
    lines = [f"Previous run ({last['run_date']}), top products by score:"]
    for row in last.get("ranked", [])[:10]:
        lines.append(
            f"- {row['name']}: score {row['score']:.1f}, "
            f"margin {row['margin_pct']:.0%}, price ${row['price']:.0f}"
        )
    return "\n".join(lines)


async def run() -> int:
    RESULTS.mkdir(exist_ok=True)
    today = date.today().isoformat()
    out_path = RESULTS / f"{today}.raw.json"

    task = (
        f"Today is {today}. Run the full research pipeline and write the JSON "
        f"output to results/{today}.raw.json.\n\n{previous_ranking(today)}"
    )

    options = ClaudeAgentOptions(
        system_prompt=PROMPT_FILE.read_text(),
        allowed_tools=["WebSearch", "WebFetch", "Read", "Write"],
        max_turns=MAX_TURNS,
        model=MODEL,
        cwd=str(ROOT),
    )

    async for message in query(prompt=task, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(block.text, flush=True)
        elif isinstance(message, ResultMessage):
            cost = getattr(message, "total_cost_usd", None)
            if cost is not None:
                print(f"\nRun cost: ${cost:.2f}", flush=True)

    if not out_path.exists():
        print(f"Agent finished without writing {out_path}", file=sys.stderr)
        return 1
    try:
        json.loads(out_path.read_text())
    except json.JSONDecodeError as err:
        print(f"{out_path} is not valid JSON: {err}", file=sys.stderr)
        return 1
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
