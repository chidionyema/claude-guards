# What a new machine needs that is not in this repository

LAW 24 says a load-bearing file belongs in git. LAW 21 outranks it and says a
secret never does. Everything caught between those two rules is listed here:
what has to exist on a new machine, what it is for, and how to get it. Never
what is in it.

`tracked.py --pull` scans every file before it copies it and refuses anything
that looks like a credential. If a refusal appears, the file belongs on this
page, by name, and the value belongs in the password manager.

## Directories whose contents are never tracked

| path | what it holds | how a new machine gets it |
|---|---|---|
| `~/.ssh` | the key that reaches GitHub and every server | generate a new key on the new machine, add the public half to GitHub. Never copy the private half between machines. |
| `~/.aws` | AWS access keys | `aws configure sso`, or paste from the password manager |
| `~/.gnupg` | the commit signing key | export from the old machine to an encrypted file, import once, then delete the file |
| `~/.config/.mono/keypairs` | a .NET strong-name keypair | regenerate; nothing depends on the old value |

## Single files whose contents are never tracked

| path | what it holds | how a new machine gets it |
|---|---|---|
| `~/.config/estate/estate.env` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | from BotFather, or the password manager |
| `~/.config/llm/secrets.sh` | `ANTHROPIC_API_KEY` | console.anthropic.com |
| `~/.config/wave/secrets.sh` | `OPENAI_API_KEY` | platform.openai.com |
| `~/.config/hermes/age-key.txt` | an age private key, decrypts the hermes secrets bundle | copy through an encrypted channel, or re-encrypt the bundle to a new key |
| `~/.config/prospector/age-key.txt` | an age private key, decrypts the prospector secrets bundle | same |
| `~/.config/gh/hosts.yml` | the GitHub CLI's oauth token | `gh auth login` once. LAW 27: once per identity, ever. |
| `~/.config/pi/config.json` | an API key for the pi bridge | from the pi bridge's own console |
| `~/.config/wave/state.json` | wave's session state, may hold a token | regenerated on first run |
| `~/.prospector/escrow/agent.pem` | the escrow agent's private key | regenerate and re-enrol the agent |
| `~/.claude/.credentials.json` | the Claude Code session | `claude` and sign in once. Ignored at `.gitignore:58`. |
| `~/.config/opencode/opencode.json` | the file IS tracked at `config/opencode/opencode.json`, with two fields stripped: `provider.minimax.options.apiKey` and `provider.minimax.options.headers.X-Api-Key` | copy the repo's version into place, then paste the MiniMax key into both fields. `tracked.py` refuses a commit that carries them (2026-08-24 10:43:31), which is why the repo's copy is short two fields rather than out of date. |

## Generated, so deliberately absent

`~/.prospector/logs`, `~/.prospector/cli_slots`, `~/.prospector/events.jsonl`,
`~/.prospector/ACTIVE`, `~/.prospector/failcount`, `~/.config/xbuild`,
`~/.config/uv/uv-receipt.json`, `~/.config/browser-harness/version-cache.json`.
LAW 24 excludes generated output. A rebuild recreates these by running.

## Repository-local git config, which git itself never tracks

`core.hooksPath` lives in a repository's `.git/config`. That file is inside the
repository and is never a tracked object, so a hook can be committed and still
be inert on a fresh clone. The hook is in git; the switch that turns it on is
not. A rebuild has to throw the switch.

| repository | command | what it turns on |
|---|---|---|
| `~/.claude/scripts` (github.com/chidionyema/claude-guards) | `git config core.hooksPath hooks` | `hooks/pre-commit`, which refuses any commit whose STAGED content matches `tracked.py`'s `SECRET` pattern |

Check it with `git config --get core.hooksPath`. Empty output means the guard is
present and doing nothing, which is the failure LAW 28 is about.

## The one step only a person can do

Signing in to prove an identity, in a browser. That is the whole of it, and
LAW 27 says it happens once per identity and never again. Everything on this
page after that first sign-in is a command, not a request to the founder.

`~/.config/agent-secrets.env.example` is a template of the above and is excluded
too. It trips the credential scanner on its placeholder values, and a tracked
file that can never pass `--check` turns the guard into noise (LAW 28). The
variable names it lists are in the tables above, which is the part that matters.
