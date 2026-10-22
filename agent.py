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
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
)

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
PROMPT_FILE = ROOT / "prompts" / "research.md"

MODEL = os.getenv("AGENT_MODEL", "claude-sonnet-5-5")
MAX_TURNS = int(os.getenv("AGENT_MAX_TURNS", "80"))
MAX_ROUNDS = int(os.getenv("AGENT_MAX_ROUNDS", "4"))
MIN_CANDIDATES = int(os.getenv("AGENT_MIN_CANDIDATES", "25"))


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

    # The agent tends to stop early when a few sources fail, so after each
    # round we check the output and send it back to keep researching.
    prompt = task
    problem = None
    async with ClaudeSDKClient(options=options) as client:
        for round_no in range(1, MAX_ROUNDS + 1):
            print(f"\n=== Round {round_no} ===", flush=True)
            await client.query(prompt)
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            print(block.text, flush=True)
                elif isinstance(message, ResultMessage):
                    cost = getattr(message, "total_cost_usd", None)
                    if cost is not None:
                        print(f"\nRun cost so far: ${cost:.2f}", flush=True)

            problem = assess(out_path)
            if problem is None:
                break
            print(f"\nNot done: {problem}", flush=True)
            prompt = (
                f"The output is not finished: {problem} Keep researching. "
                "Try sources you have not used yet: Google Trends rising queries, "
                "TikTok Creative Center, Exploding Topics, Etsy trend reports, "
                "Jungle Scout or Helium 10 blog lists, Alibaba product pages for "
                "factory costs, and Reddit threads found through search. If a page "
                "fails to load, search for coverage of it instead of giving up. "
                f"Then rewrite the full file at results/{out_path.name}, keeping "
                "every candidate you already have."
            )

    if problem is not None:
        print(f"Stopping after {MAX_ROUNDS} rounds: {problem}", file=sys.stderr)
        if not out_path.exists() or "not valid JSON" in problem:
            return 1
        print("Scoring the partial results anyway.")
    print(f"Wrote {out_path}")
    return 0


def assess(path: Path) -> str | None:
    """Returns what is still missing from the output, or None if it is complete."""
    if not path.exists():
        return f"results/{path.name} has not been written."
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as err:
        return f"results/{path.name} is not valid JSON ({err})."
    live = [c for c in data.get("candidates", []) if not c.get("kill_reason")]
    if len(live) < MIN_CANDIDATES:
        return (
            f"only {len(live)} candidates have full economics; "
            f"the target is at least {MIN_CANDIDATES}."
        )
    return None


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
