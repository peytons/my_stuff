# empower-mcp

Local-only, **read-only** MCP server for [Empower Personal Dashboard](https://home.personalcapital.com)
(formerly Personal Capital). Runs as a stdio subprocess launched by Claude
Desktop / Claude Code — no HTTP listener, no remote hosting, no cloud storage
of credentials or data.

> **Heads up:** this talks to Empower's undocumented internal API — the same
> one their web dashboard uses. There is no official consumer API, so auth is
> fragile by nature. If Empower changes their login flow, `setup` may break
> until this client is updated.

## Tools exposed

| Tool | What it returns |
|---|---|
| `get_accounts` | All linked accounts: name, institution, type, balance, last-synced |
| `get_transactions(start_date, end_date, account_id?, category?)` | Date, merchant, amount, category, account, pending/posted |
| `get_net_worth(as_of_date?)` | Current net worth + daily historical snapshots when available |
| `get_holdings(account_id?)` | Positions: symbol, quantity, value, cost basis when available. Options positions won't have strike/expiration/Greeks — only what Empower's dashboard shows |
| `get_cash_flow(start_date, end_date)` | Income vs. spending summary, by category |

Everything is GET-equivalent. There is deliberately no code path that can
write, transfer, or modify anything.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)

## First-time setup (2FA)

Run this **once, in a real terminal** (not inside Claude — it's interactive):

```sh
cd /path/to/empower-mcp
uv run empower-mcp setup
```

It will:

1. Prompt for your Empower email and password (password is read without echo
   and never stored, printed, or logged).
2. Trigger a 2FA challenge (choose `sms` or `email`) and prompt for the code.
   If Empower already trusts this device, the 2FA step is skipped.
3. Persist the resulting session to `~/.config/empower-mcp/session.json`
   with `chmod 600`, and verify it by fetching your account list.

Check session health any time with:

```sh
uv run empower-mcp status
```

## Wiring into Claude Desktop

Add to `claude_desktop_config.json` (macOS:
`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "empower": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/ABSOLUTE/PATH/TO/empower-mcp",
        "empower-mcp",
        "serve"
      ]
    }
  }
}
```

Restart Claude Desktop after editing. For Claude Code:

```sh
claude mcp add empower -- uv run --directory /ABSOLUTE/PATH/TO/empower-mcp empower-mcp serve
```

## Session file & re-authenticating

- The session (cookies + CSRF token) lives at
  `~/.config/empower-mcp/session.json`, permissions `600`. Override the
  directory with `EMPOWER_MCP_CONFIG_DIR` if you want it elsewhere.
- Sessions eventually expire server-side. When that happens, tools return a
  clear error telling you to **re-run `empower-mcp setup`** — they will never
  re-prompt for credentials mid-conversation.
- `uv run empower-mcp logout` deletes the local session file.

## Manual test

After setup and wiring into Claude Desktop:

1. Ask Claude: **"What's my net worth?"** — it should call `get_net_worth`
   and report the same figure as the Empower dashboard's top line.
2. Ask: **"List my linked accounts"** — should call `get_accounts` and match
   the dashboard's account sidebar.
3. Ask: **"What did I spend on restaurants last month?"** — should call
   `get_transactions` or `get_cash_flow` with a sensible date range.
4. To test expiry handling: run `uv run empower-mcp logout`, restart Claude
   Desktop, and ask for net worth — the tool should fail with a message
   telling you to re-run `empower-mcp setup`.

## Security notes

- Read-only by design; no write/transfer endpoints are implemented.
- stdio transport only — no network listener of any kind.
- Credentials are never hardcoded, stored, or logged; only the session
  cookie file is persisted, locally, mode 600.
- `session.json` and `.env` are gitignored.
- Requests are throttled (≥1s apart) and retried with exponential backoff on
  429/5xx — be gentle with an undocumented API.

## Prior art

Auth flow and endpoints are based on
[haochi/personalcapital](https://github.com/haochi/personalcapital),
[empower-personal-capital](https://pypi.org/project/empower-personal-capital/),
and the community wrappers under the
[personal-capital GitHub topic](https://github.com/topics/personal-capital).
