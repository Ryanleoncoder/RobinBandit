# Security

## Reporting a vulnerability

Open a [security advisory](https://github.com/Ryanleoncoder/RobinBandit/security/advisories/new)
instead of a public issue. If that is not available to you, open an issue saying
only that you found something and asking for a private channel — no details in
the open.

This is a personal project, not a company: expect a human answer, not an SLA.

## What this project holds, and where

RobinBandit stores API keys. Knowing where they live matters more here than in
most tools.

Everything lives under `~/.robinbandit/`:

| file | holds |
|---|---|
| `cofre.json` | the API keys — written atomically, `0600` where the OS supports it |
| `contas.json` | account and chain choices; no key values, only variable names |
| `ranking.json` | what the router learned: counters and Beta parameters |
| `historico.json` | calls per day per provider: how many succeeded, how many failed |
| `janelas.json` | subscription block usage, to know when it turns over |
| `uso.json` | token counts per day |

Nothing is written inside the repository, and nothing is sent anywhere. Change
the location with `ROBINBANDIT_VAULT_PATH` and `ROBINBANDIT_ACCOUNTS_PATH`.

**Prompts and responses are never stored.** The router records what happened —
succeeded, failed, how long it took — never what was said. The one piece of text
that is kept is the provider's own error message, truncated to 80 characters in
`historico.json`, so the panel can say *why* a day was bad.

## Design decisions that are security decisions

**Key values never leave the vault in a response.** Every status payload carries
only the variable name and a hint with the last characters (`...6789`). The same
holds for the CLI: `robinbandit chave list` shows the hint, never the key.

**The YAML never holds a key.** It holds `api_key_env`, the *name* of the
variable. That is what makes a configuration file safe to commit.

**Only variables the catalog declares can be written.** A request naming an
unknown variable is refused, so neither the panel nor the CLI can be used to
write arbitrary configuration into the vault.

**Subscription providers are driven through their official CLI.** For
`claude_code` and `chatgpt_codex`, RobinBandit never opens
`~/.claude/.credentials.json` or `auth.json`, never copies access or refresh
tokens, and never writes those sessions into its own vault. The CLI owns the
session.

**The `.env` is read, never written.** RobinBandit loads keys from a project
`.env` if one is there, and leaves the file untouched.

## The server has no authentication — on purpose

RobinBandit is a local proxy, like Ollama, LM Studio and the other LLM gateways
it sits next to. The endpoint and the panel have **no authentication**: what
protects them is listening on `127.0.0.1`, where only processes on your own
machine can reach them.

The API key field you paste into Claude Code or Cline is a placeholder. Those
tools require the field to be filled; the server does not check it.

**This means `--host 0.0.0.0` exposes everything**: your quotas, and the routes
that read and write credentials. Do not use it on a machine reachable from the
internet.

On a server, keep the default and reach the panel through a tunnel:

```bash
ssh -L 8000:localhost:8000 user@host
```

Your ssh key does the authenticating, which is better than anything this project
would implement on its own. To configure a remote machine without a browser at
all, use the CLI (`robinbandit chave add ...`) over ssh.

## Supported versions

The latest release. This project has no long-term support branches.

## Scope

In scope: key leaking into responses, logs or payloads; writes outside the
declared paths; the allow-list being bypassed; anything that sends prompts,
responses or keys somewhere they were not meant to go.

Out of scope: the absence of authentication on `127.0.0.1` (documented above and
intentional), and vulnerabilities in the providers themselves.
