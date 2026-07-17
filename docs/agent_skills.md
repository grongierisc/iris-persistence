# AI agent skills

`iris-persistence` ships three portable skills for AI coding agents:

- `iris-persistence-models` builds models, configures runtimes, implements CRUD and queries, and adds tests.
- `iris-persistence-scaffold` generates safe observe-mode models from existing IRIS classes.
- `iris-persistence-migrations` plans, reviews, applies, verifies, and rolls back schema migrations.

The skills use the open `SKILL.md` format and work with Codex, Claude Code, Cursor, and other compatible agents.

## Quick install

Install from GitHub without cloning this repository:

```bash
npx skills add grongierisc/iris-persistence
```

The interactive installer lets you select skills, target agents, installation scope, and whether to copy or symlink the files. It requires Node.js and downloads the `skills` CLI through npm.

Restart the target agent or begin a new session after installation.

## Install all skills for one agent

Codex:

```bash
npx skills add grongierisc/iris-persistence \
  --skill '*' \
  --agent codex \
  --global \
  --yes
```

Claude Code:

```bash
npx skills add grongierisc/iris-persistence \
  --skill '*' \
  --agent claude-code \
  --global \
  --yes
```

Remove `--global` to install into the current project instead of the user-level skills directory. Remove `--yes` to review the choices interactively.

## Install one skill

```bash
npx skills add grongierisc/iris-persistence \
  --skill iris-persistence-models
```

Available names:

```text
iris-persistence-models
iris-persistence-scaffold
iris-persistence-migrations
```

List the available skills without installing:

```bash
npx skills add grongierisc/iris-persistence --list
```

## Choose the installation scope

| Scope | Command | Use when |
| --- | --- | --- |
| Current project | `npx skills add grongierisc/iris-persistence` | A project should share and version its agent configuration. |
| User/global | Add `--global` | The skills should be available in every project for that user. |
| Specific agent | Add `--agent codex` or `--agent claude-code` | Only one installed agent should receive the skills. |

Project scope is the default. Prefer it for application repositories that depend on a particular `iris-persistence` version. Use global scope for personal development across many projects.

## Update or remove

Check and install updates with:

```bash
npx skills update
```

Remove these skills interactively with:

```bash
npx skills remove
```

Use the CLI's `--global`, `--agent`, and skill-name options to target the same scope used during installation.

## Native Codex installation

Codex users can install directly from a GitHub skill directory by asking the built-in installer:

```text
$skill-installer install https://github.com/grongierisc/iris-persistence/tree/main/skills/iris-persistence-models
```

Repeat with `iris-persistence-scaffold` and `iris-persistence-migrations`, then restart Codex. The `npx skills` flow remains the recommended option when installing several skills or supporting multiple agents.

## Use the skills

Skills can trigger from a matching task or be selected explicitly:

```text
Use $iris-persistence-models to add an Order model with line items.
Use $iris-persistence-scaffold to scaffold App.* into generated/models.
Use $iris-persistence-migrations to plan and review the schema change.
```

The source packages live under [`skills/`](../skills/) and include Codex UI metadata in each `agents/openai.yaml` file.
