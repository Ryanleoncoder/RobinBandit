<p align="center">
  <img src="assets/robinbandit_logo1.png" alt="RobinBandit" width="420">
</p>

<p align="center">
  <a href="https://github.com/Ryanleoncoder/RobinBandit/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/Ryanleoncoder/RobinBandit/actions/workflows/ci.yml/badge.svg"></a>
  <img alt="Python 3.9+" src="https://img.shields.io/badge/python-3.9%2B-5E7A61?style=flat-square&labelColor=000000">
  <img alt="Zero dependencies in the core" src="https://img.shields.io/badge/core-zero%20dependencies-E0AF43?style=flat-square&labelColor=000000">
  <a href="LICENSE"><img alt="MIT" src="https://img.shields.io/badge/license-MIT-EFE3D2?style=flat-square&labelColor=000000"></a>
</p>

# RobinBandit

[Português](README.md) · **English**

An adaptive router for multiple LLM providers. It sits between your agent and
the providers, and picks where each call goes based on what happened on the
previous ones.

```bash
pipx install "robinbandit[server,yaml,providers]"
robinbandit serve
```

That's it. The panel opens in your browser on its own, and **four providers come
up with no API key at all** — Claude Code and ChatGPT Codex through the
subscription you already pay for, plus the free ones. No `pipx`? `pip install`
works the same.

Then, in the **Connect** tab, the panel hands you ready-made configuration to
paste into Claude Code, Codex, Cline, OpenCode, the OpenAI SDK or curl.

**41 providers in the catalog** — 13 with a free tier, 4 local, 2 by
subscription, the rest by key. None of them opts in by itself: turning one on
means putting its name in `chain_order`.

**[See the project page →](https://ryanleoncoder.github.io/RobinBandit/)**

![The current queue in the panel: each provider with state, quality, OK/error, latency and the reason whoever is waiting is waiting](docs/imagens/painel-agora.png)

<p align="center"><sub>The panel at <code>/painel</code>: the order right now, and the reason for it.</sub></p>

Instead of keeping a fixed fallback order, RobinBandit watches the outcome of
previous calls and reorders providers by context, quality, latency, availability
and quota.

The project started inside [CX-GAME](https://github.com/Ryanleoncoder/CX-GAME),
as Logun's provider router, and was later split into a package of its own.

## Contents

**Understand** · [The problem](#the-problem) · [How it decides](#how-it-decides) ·
[Context](#context) · [Health and quality](#health-and-quality) ·
[Cold start](#cold-start) · [How it learns, in detail](docs/como-aprende.md)

**Use** · [Usage](#usage) · [YAML configuration](#yaml-configuration) ·
[Credentials](#credentials-and-secrets) · [Panel](#panel) ·
[Two protocols](#two-protocols-one-router) · [CLI](#cli)

**No API key** · [ChatGPT Codex](#chatgpt-codex-oauth) ·
[Claude Code](#claude-code-subscription)

## The problem

A traditional chain usually works like this:

```text
Provider A → failed → Provider B → failed → Provider C
```

If the first provider starts returning `429`, gets slow or degrades, it is still
first in line on the next call.

And a bad day is not hypothetical:

![Thirty days per provider: gemini at 98.46% with two bad days from 429s, claude_code at 97.3% with one 529 overloaded day, cerebras and groq with none](docs/imagens/dia-ruim.png)

None of these providers is broken — all four clear 97%. The point is that
failure is not spread evenly: it clumps into days, with a reason attached
(`429 rate limit`, `529 overloaded`), and on one of them `gemini` was the worst
possible pick while `groq` ran at 100%. A fixed order has no way to know that.

The enemies here are **quota, cost, latency and quality drift**.

The goal is to stop insisting on providers that are already showing signs of
degradation and, among those available, to favor the ones answering better.

## How it decides

The screenshot above is that decision happening. `groq` has 140 good calls and 6
errors, `claude_code` has 58 and 1 — both are **waiting**, and the *why* column
says for how much longer (265.8s and 27.8s). `cerebras` took first place, with
31 calls, 0 errors and 324ms.

Nobody edited a config file to make that happen. It is the difference between a
router and a fallback list: in the list, `groq` would still be first in line on
the next call.

On every `order()` call, each provider gets a score:

```python
score = w_q * quality_thompson
      + w_l * (1 - latency_norm)
      + w_s * health_thompson
      + tier_bonus
      + priority_bonus
      + profile_bonus
      - cost_penalty
      - quota_penalty
      - inflight_penalty
```

The signals used are:

* **quality:** Thompson Sampling per `(context, provider)`;
* **latency:** Peak EWMA;
* **health:** a Beta Thompson Sampling kept separate from quality;
* **quota:** when the provider reports how much is left;
* **inflight:** number of open calls;
* **tier:** declared economic preference;
* **priority:** explicit preference from the YAML;
* **cost:** configurable penalty per `cost_class`;
* **profile:** per-task preference (`analysis`, `coding`, and so on).

Providers in cooldown go to the end of the queue, but stay available in case the
others fail too.

### Peak EWMA

Latency uses Peak EWMA, in the same spirit as systems like Envoy and Finagle.

A spike affects the score immediately. Recovery happens gradually, sample by
sample.

### Concurrency

`begin()` and `end()` track the number of open calls per provider.

Inflight enters as a small, bounded penalty, saturating at `0.15`. It helps
spread traffic between comparable providers, without turning the router into a
uniform balancer.

In a test with 24 concurrent calls and 3 equivalent providers, the highest
observed peak dropped from 10 to 9 simultaneous calls per provider. A perfectly
uniform distribution would be 8.

When one provider is clearly better, traffic still concentrates on it.

RobinBandit implements neither bulkheads nor a hard concurrency limit per
provider.

## Context

Context is a string used to separate learning cells.

```python
await chain.complete(messages, context="audit")
await chain.complete(messages, context="autocomplete")
```

In universal mode the context is opaque. Under `agent_mode: sentury`, the facade
combines profile and complexity (for example, `coding:CRITICAL`).

You can use task type, language, tenant, tier or any other classification that
makes sense for your application.

With no context, everything falls into the `default` cell, working as a global
per-provider bandit.

Weights can vary per context too:

```python
router = ProviderRouter(
    priors,
    weights={
        "audit": (0.60, 0.15, 0.25),
        "autocomplete": (0.20, 0.50, 0.30),
    },
)
```

The weight order is:

```text
(quality, latency, success)
```

The default is:

```python
(0.40, 0.30, 0.30)
```

Thompson Sampling is one component of the score. Latency, success, quota and
inflight keep taking part in the decision.

## Health and quality

In the *Quality* column of the screenshot above, providers that already ran show
a learned number (`cerebras` 0.72, `cohere` 0.68), and those that never ran show
the prior, marked as a **guess**. Without feedback the column reflects
operational health; with `reward_quality`, it starts reflecting judged quality.

A call with HTTP `200` may well have produced a bad answer.

That is why there are two feedback channels:

```python
router.record_success(provider)
router.record_failure(provider)

router.reward_quality(
    provider,
    context="audit",
    good=True,
)
```

`record_success` and `record_failure` record operational health.

`reward_quality` records a judgment of the answer.

The channels use independent Beta distributions. An HTTP 200 never raises
`quality_mean`, and a reviewer's feedback never touches `health_mean`.

What counts as a "good answer" is up to whoever uses the router. Feedback can
come from a reviewer, an automated test, a user, or another component of the
application.

If `reward_quality` is never used, learning continues on the operational signals
alone.

## Recency

Before each reinforcement, the cell applies:

```python
decay = 0.99
```

Accumulated mass is capped as well.

With that, old observations lose influence gradually and recent changes start
affecting routing.

## Cold start

A new cell starts from the `quality` set in the provider's prior, with mass
equivalent to roughly six observations.

```python
providers = {
    "groq": {"tier": 1, "quality": 0.75},
    "gemini": {"tier": 1, "quality": 0.80},
}
```

Without `quality`, the starting value is `0.6`.

This lets new providers take part in routing even with no history. In the panel,
those providers show their quality marked as a **guess** until the first real
call.

> This is not a neural network: it is Bayesian reinforcement learning, with no
> `torch`, `sklearn` or `numpy`. The reasoning behind that choice, with the code
> for each mechanism, is in **[docs/como-aprende.md](docs/como-aprende.md)**
> (in Portuguese).

## Usage

```python
from robinbandit import ChainProvider, ProviderRouter

router = ProviderRouter(
    providers={
        "groq":   {"tier": 1, "quality": 0.75},
        "gemini": {"tier": 1, "quality": 0.80},
        "demo":   {"tier": 9, "quality": 0.05},
    },
    last_resort="demo",
)

chain = ChainProvider(
    [groq, gemini, demo],
    router,
)

response = await chain.complete(
    messages,
    context="audit",
)
```

### Per-request selection

The Router supports three policies without confusing choice with fallback:

```python
from robinbandit import RouteSelection

RouteSelection.router()                 # the Router decides everything
RouteSelection.hybrid("groq:model-a")   # try the pinned one, then fall back to the Router
RouteSelection.strict("groq:model-a")   # only the pinned one; fails with no fallback
```

In the Sentury profile, `router`, `reforçado` and `dedicado` are aliases for
those three behaviors. In the universal API the canonical names are `router`,
`hybrid` and `strict`; `auto` is accepted only as a legacy alias for `router`.

## YAML configuration

Install `robinbandit[yaml,providers]` and load a configured facade:

```python
from robinbandit import RobinGateway

gateway = RobinGateway.from_yaml("config/universal.yaml")
```

`agent_mode: universal` keeps the context entirely under the agent's control.
`agent_mode: sentury` understands `complexity` and `profile` and combines them
into a cell such as `analysis:CRITICAL`. Providers, tiers, priorities, cost
classes, models and references to key variables live in the YAML; secrets never
do. See `config/universal.example.yaml` and `config/sentury.yaml`.

Since version 0.4, `tier`, `quality`, `priority`, `cost_class`, profiles and
models take part in the decision. Health, cooldown and quota are learned per
provider; quality, latency and failures are learned per `provider:model`.

The YAML is executable: `build_provider_set(config, settings)` builds Groq,
Gemini, OpenRouter, Anthropic and any declared OpenAI-compatible endpoint.
`settings` is optional and works only as a source of `.env` values; Robin
imports no type from the consuming agent.

Extra accounts can also live under `accounts.items`, always using `key_env`
instead of the key value. `accounts.tiers` picks which account serves a special
selection. In the Sentury profile, `selection_tier: ultra` and `ultra_max`
provide the defaults for Reinforced and Dedicated; a choice saved from the panel
is a mutable layer on top of the YAML and takes effect on the next call.

### Credentials and secrets

The YAML never holds a key. `api_key_env` points at the allowed name, and the
resolver uses the precedence **what the caller passed > vault > environment**.
Whoever builds a provider with `settings` in hand chose that value; the
environment is the default for whoever chose nothing. With the environment
first, a `.env` loaded into the process would silently override explicit
configuration.

The vault writes atomically, tries to apply `0600` permissions, supports
CSV/list pools, and never returns the value in status payloads. Use
`ROBINBANDIT_VAULT_PATH` (universal) or the compatible alias
`SENTURY_VAULT_PATH`.

The catalog, the vault and the account choices belong to RobinBandit itself.
Reinforced with no credential records the target's failure and carries on
through the Router; Dedicated with no credential ends with no fallback. Changing
a key rebuilds the Sentury adapters without requiring a restart.

#### ChatGPT Codex (OAuth)

The `codex_app_server` adapter is the intentional exception to the `api_key_env`
model: it uses the official CLI as the owner of the OAuth session and talks to
`codex app-server` over JSONL. Robin never opens `auth.json`, never copies
access/refresh tokens, and never writes the session into your vault.

```bash
npm install -g @openai/codex
codex login
codex login status
```

With the CLI authenticated, `build_provider_set()` includes `chatgpt_codex`
automatically. With no CLI or no login, it stays out of the chain like any
unconfigured provider. `CODEX_BINARY` picks a different executable, and
`CHATGPT_CODEX_MODELS` overrides, via CSV, the order declared in the YAML.

Each completion uses an ephemeral thread, a read-only sandbox, `never` approval,
and disables shell, plugins, apps, browser, computer, image and subagents. That
keeps Codex as Robin's model; tools and side effects stay under the host agent's
control. The catalog shows only `auth_type: codex_cli` and the configured state,
never authentication material.

The YAML field `icon: openai` is a semantic identifier only. The host agent owns
the visual asset and decides how to present it; Robin stays uncoupled from any
particular frontend and imposes no image on universal integrations.

#### Claude Code (subscription)

The `claude_code` adapter follows the same principle as Codex: the official CLI
owns the session, and Robin never opens `~/.claude/.credentials.json`.

```bash
npm install -g @anthropic-ai/claude-code
claude          # log in the first time
claude --version
```

The binary is also found inside the editor extension
(`~/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/`), which
is where it lives when you use Claude Code through VS Code without installing
the global package. `CLAUDE_CODE_BIN` points at a different executable;
`CLAUDE_CODE_MODELS` overrides the list via CSV.

Each call runs with `--allowed-tools ""`: here Claude Code is a model provider,
and the tool loop stays with the host agent. Two loops in the same turn would
fight over the same execution.

What this unlocks is the heavy work — 1M context, long reasoning — with no API
key and no per-token quota, through the subscription you already pay for.

![Subscription windows: chatgpt_codex and claude_code with the time left in their 5-hour block](docs/imagens/painel-janelas.png)

<p align="center"><sub>A subscription does not get slow when usage runs out: it stops, and comes back at a knowable time.</sub></p>

A subscription has no per-token quota to query — it has a block. The *Windows*
tab shows how long until each block turns over, how many calls went into it, and
how many times it stopped at the limit. That is enough to decide between waiting
and switching providers. Note that there is no key field on either card.

Hitting that limit does **not** hurt the provider in the ranking: the block
running out is not the provider degrading, so health is left untouched and the
cooldown waits exactly until the window turns over.

A provider needs to implement:

```python
async def complete(messages, temperature):
    ...
```

It may also expose:

```text
name
last_model
last_quota
```

If `complete()` accepts `context`, `ChainProvider` passes the value along.

The signature is detected with `inspect.signature`. That avoids treating a
`TypeError` raised inside the provider as a signature mismatch and repeating the
call.

### `last_resort`

A provider set as `last_resort` stays at the end of the chain.

It also accumulates no quality evidence in the bandit.

It is useful for local fallbacks or providers used only as a last resort.

## Panel

```bash
robinbandit serve          # brings up the endpoint
# open http://localhost:8000/painel
```

One page, served by the package itself. It shows the order right now and **why**
it looks that way — quality, success rate, latency and the reason whoever is
waiting is waiting. It computes nothing: everything comes from the router,
because a panel that does its own math shows one thing while the router decides
another.

There are seven tabs. What each one solves:

### Providers — what `tier` means

![Providers grouped by tier, with a choice between letting the bandit learn and letting the tier decide](docs/imagens/painel-provedores.png)

A tier is a group, and several providers fit in the same one. What changes is
the weight it carries at decision time, and that is a choice between two:

* **Let it learn** (`strategy: adaptive`) — the tier is a bonus. A tier 2
  provider that has been answering better goes ahead of tier 1.
* **My tier rules** (`strategy: tier`) — the tier is a barrier. Tier 2 is only
  tried once all of tier 1 has failed: *"try these first even if they fail; only
  then spend my credits"*.

Dragging changes the group; the button removes a provider from the chain and
puts it back.

### Models — each provider's list

![Each provider's model list, in order, with a button to ask the provider what it has today](docs/imagens/painel-modelos.png)

Once a provider is picked, it tries the models on this list top-down and stops at
the first one that answers. `GET /modelos/{provider}` asks the provider what it
has today, instead of trusting a list written months ago.

### Credentials — the key never comes back

![Accounts and credentials: keys in the vault, accounts per provider, and who serves Reinforced and Dedicated](docs/imagens/painel-credenciais.png)

A key pasted here goes into the machine's vault with `0600` permissions and
**never comes back in any payload** — not the start of it, not the end. A
provider can have more than one account, and the rotator alternates between them
when one hits its quota. The two boxes at the top pick which account serves
`Reinforced` and `Dedicated`.

*Bring into the vault* copies what today only exists in the environment; the
source `.env` is not touched.

### Usage — tokens, not currency

![Tokens spent: a 30-day total, call count, and a one-square-per-day calendar](docs/imagens/painel-uso.png)

Every provider already reports what a response cost, and that number used to be
read within the turn and thrown away. Here it stays: one square per day, darker
on the days you spent more.

In tokens, not currency, on purpose — prices change by model, by region and by
promotion, and a cost computed from a stale table lends the confidence of an
exact number to an out-of-date guess.

### Connect — plugging in a tool

![The Connect tab, with ready-made configuration for Claude Code, Codex, Cline, OpenCode, the SDK and curl](docs/imagens/painel-conectar.png)

`GET /cli-tools` returns ready-made configuration for each client to point here
— Claude Code, Codex, Cline, OpenCode, the SDK and curl. Nothing is written to
disk: changing your own configuration is your call.

Once a tool has called through, the tab says so — how many calls, how long ago,
and which contexts it used. Copying configuration and having no way to tell
whether it landed left that check to the first error inside the agent, which is
the worst place to find out.

The `model` field becomes the bandit's **context**, not the name of a model:
`model="code"` learns in one cell, `model="triage"` in another.

## Using the router alone

`ChainProvider` is not required.

```python
ordered = router.order(context="audit")
```

Your own execution layer can use that order and then feed the router:

```python
router.record_success(provider)

router.record_failure(provider)

router.reward_quality(
    provider,
    context="audit",
    good=True,
)
```

## Persistence

Learned state can be serialized:

```python
state = router.dump()
```

And restored later:

```python
router.load(state)
```

`dump()` returns a JSON-compatible dictionary and can be saved to a file, Redis,
Upstash or any other storage.

Cooldown, current status and quota information do not enter the dump, because
they represent temporary process state.

Since version 0.2, the dump has separate `health` and `quality` maps. `load()`
accepts the old 0.1 format with `cells`, migrating those cells into `health`;
the old quality was mixed together and cannot be reconstructed honestly.

## Two protocols, one router

The `server` extra exposes the router through two APIs, because the tools do not
speak the same language:

| route | protocol | who speaks it |
|---|---|---|
| `POST /v1/chat/completions` | OpenAI | Codex, Cline, OpenCode, the OpenAI SDK, curl |
| `POST /v1/messages` | Anthropic | Claude Code |

Claude Code does **not** speak the OpenAI format: it calls `/v1/messages`, with
`system` as a separate field and `content` in blocks. Both routes land on the
same `ChainProvider` and the same bandit — only the translation in and out
differs.

`/v1/messages` accepts `stream: true` and answers in SSE, but the text comes out
whole in a single event: Robin's `complete()` returns the finished response, and
faking it token by token would be theater. `/v1/chat/completions` refuses
streaming with `400`.

### OpenAI-compatible endpoint

```bash
pip install "robinbandit[server]"
pip install "robinbandit[yaml,providers]"
```

```python
from robinbandit.server import create_app

app = create_app(
    [groq, gemini, demo],
    router,
)
```

Run it with:

```bash
uvicorn app:app
```

Then point a compatible client at the endpoint:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-used",
)

response = client.chat.completions.create(
    model="audit",
    messages=[...],
)
```

The `model` field is used as the bandit's context:

```text
model="audit"  → context "audit"
model="triage" → context "triage"
```

That makes it possible to separate learning cells even in clients that know
nothing about RobinBandit's own API.

Clients using Ollama's OpenAI-compatible layer can point at the same endpoint.

## Feedback

The OpenAI protocol has no standard field for quality feedback.

RobinBandit adds a separate endpoint:

```text
POST /v1/chat/completions
        ↓
id: chatcmpl-abc

POST /feedback
{
  "id": "chatcmpl-abc",
  "good": true
}
```

The `id` ties the feedback to the decision that produced that response,
including provider and context.

Feedback may arrive well after the original response.

Up to 10,000 decisions can stay waiting for feedback. Past that limit, the
oldest are dropped.

Without `/feedback`, the endpoint keeps learning from the operational signals.

Also available:

```text
GET /v1/models
GET /state
```

### Server limitations

The server does not implement:

* authentication;
* key management for its own clients;
* budget;
* universal token counting.

It is a local proxy, like the tools it sits next to: what protects it is
listening on `127.0.0.1`, not a password. On a VPS, keep it on localhost and
reach the panel through an ssh tunnel
(`ssh -L 8000:localhost:8000 user@host`).

Token-by-token streaming does not exist either: `/v1/messages` packs the
finished response into SSE for clients that only know that format, and
`/v1/chat/completions` refuses `stream: true` with `400`.

The `usage` field is omitted when the provider does not supply that information.

## CLI

The panel is for understanding; the CLI is for doing without a browser, which is
what a server needs.

```bash
robinbandit serve                      # endpoint and panel; the browser opens on its own
robinbandit key add GROQ_API_KEY ...    # store a key in the vault
robinbandit key list                   # what is configured (never shows the value)
robinbandit providers                  # who is in the chain
robinbandit state state.json           # what the router learned
robinbandit language pt                # which language it answers in
```

`serve` detects whether there is a screen: on a machine with no graphical
session — a server, a container, ssh — it does not try to open a browser, and
`--no-browser` forces that anywhere.

`key add` takes `-` instead of the value to read from standard input, which
keeps the key out of your shell history:

```bash
cat key.txt | robinbandit key add GROQ_API_KEY -
```

`providers on X` and `providers off X` add and remove a provider from
the chain. Both write to the same file the panel writes to, and take effect on
the next start.

`state` reads a file in `ProviderRouter.dump()` format and shows the learned
state: counters, latency, quality, sample counts and the alpha/beta parameters
of each cell.

In an interactive terminal, RobinBandit also prints the logo in Braille.

```bash
robinbandit state state.json --no-color
robinbandit state state.json --no-banner
```

The filename is still accepted directly, with no subcommand
(`python -m robinbandit state.json`), the way it worked before `serve` existed.

In pipes and redirections, the banner is omitted automatically.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The core uses only the Python standard library.

Extra dependencies live in the extras:

```bash
pip install "robinbandit[server]"
```

The server uses FastAPI and Uvicorn.

The tests use `pytest` and `pytest-asyncio`.

## Out of scope for now

RobinBandit is a provider router and gateway. It does not yet implement:

* per-provider bulkheads;
* a rate limiter;
* client authentication on the server;
* a hard spending ceiling with universal token/price accounting;
* shadow routing.

Cost already takes part in the objective function through its declared class,
but it is not an exact per-token bill. Used as a package, `reward_quality`
accepts a provider and a model; on the server, `/feedback` correlates delayed
rewards by the response id.

## Identity

| Color | Hex | Where |
|---|---|---|
| Beige | `#EFE3D2` | the letter, and text on a dark background |
| Green | `#5E7A61` | the speed bars, the "BANDIT" |
| Amber | `#E0AF43` | the eye — the single point of emphasis |
| Black | `#000000` | the background |

The logo in `assets/robinbandit_logo1.png` comes in a version for dark
backgrounds and one for light. The amber appears exactly once, on purpose: it is
what the eye looks for first.

## License

MIT — see [LICENSE](LICENSE).
