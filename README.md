# Product research agent

Finds physical products that look profitable to sell online. Every Monday it researches trending products, notes what each product needs to sell legally, kills anything low margin, ranks the rest, and posts the top 5 to Discord. The full report is committed to `results/`.

## How it works

1. `agent.py` runs a Claude agent with web search. It gathers candidates, notes regulatory requirements per `prompts/research.md`, and writes raw inputs (price, factory cost, freight, duty rate, fees, ad cost estimates, trend scores) to `results/<date>.raw.json`.
2. `score.py` does all the math. For each product:

   ```
   landed = unit_cost + freight + unit_cost * duty_rate
   fees   = price * platform_fee_rate + fulfill_fee
   CAC    = cost_per_click / conversion_rate
   margin = orders_per_customer * (price - landed - fees) - CAC
   ```

   Products under 25% margin after ad costs are killed. The rest are scored with the weights at the top of `score.py` and written to `results/<date>.md`.
3. The GitHub Actions workflow runs both every Monday and commits the results, so each run can compare against the last one.

## Setup

1. Create a private GitHub repo and push these files to it.
2. On your Mac, install the Claude CLI (`npm install -g @anthropic-ai/claude-code`) and run `claude setup-token`. Log in with your Claude account when the browser opens, then copy the token it prints. Add it as a repo secret named `CLAUDE_CODE_OAUTH_TOKEN` (Settings, then Secrets and variables, then Actions). Runs count against your Claude plan's usage limits, with no separate API bill.
3. In a Discord server you own, go to Server Settings, then Integrations, then Webhooks, and create a webhook for a channel. Add its URL as a repo secret named `DISCORD_WEBHOOK_URL`.
4. Open the Actions tab, pick `weekly-product-research`, and click "Run workflow" to test it. After that it runs on its own every Monday.

## Run locally

```bash
pip install -r requirements.txt
npm install -g @anthropic-ai/claude-code
claude   # log in with your Claude account once, then exit
python agent.py && python score.py
```

The "Run cost" line in the log is what the run would cost at API prices. On a subscription it is an estimate of usage, not a charge.

## Paying per use instead

If you hit your plan's limits, get an API key at https://console.anthropic.com, add it as a secret named `ANTHROPIC_API_KEY`, and swap the env line in `.github/workflows/weekly-research.yml` as its comment describes. Set a monthly spend limit in the Console first.

## Tuning

- `AGENT_MODEL` and `AGENT_MAX_TURNS` environment variables control the model and how long the agent can research.
- Change `MIN_CUSTOMER_REVENUE`, `MAX_PRICE`, `MIN_MARGIN_PCT`, and `WEIGHTS` in `score.py`.
- `AGENT_MIN_CANDIDATES` (default 25) and `AGENT_MAX_ROUNDS` (default 4) control how hard the agent is pushed to keep researching when it stops early.
- Once you test real products with ads, compare the predicted CAC and margin to what actually happened and adjust the weights.
