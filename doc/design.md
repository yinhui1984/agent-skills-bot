# Agent Skills Bot MVP Design

## Goal
Build a global (not project-scoped) agent that supports a Claude-like skill system (SKILL.md + optional scripts) and a minimal toolset. The MVP focuses on the core data flow and a single universal tool (bash_tool). The design is model-agnostic and avoids tight coupling to any specific LLM provider.

## Key Decisions
- **Scope**: Global access (not bound to a single repo).
- **Skills**: Standard SKILL.md files following the AgentSkills specification: https://agentskills.io/specification
- **Tools**: MVP provides a single `bash_tool` that can run standard Unix commands (cat, echo, which, git, python3, foundry, etc.).
- **Reasoning**: Only task understanding and tool selection use the LLM; everything else is deterministic logic code.
- **Model Independence**: The agent should work with any compatible chat-completion API; provider-specific code is isolated behind an adapter.
- **Default UI**: CLI is the primary interface (`main_cli.py`).
- **Default Model**: DeepSeek V3 with JSON mode output for strict formatting.

## Directory Layout (proposed)
```
~/.agent-skills-bot/skills/
  public/
  user/
  downloaded/
```
Each skill directory contains `SKILL.md` with frontmatter `name` matching the directory name (lowercase kebab-case) and a non-empty `description`.
If a skill needs a custom executable entrypoint, use `metadata.entrypoint` in the frontmatter (extension field).

## Core Components
1. **CLI / API Entry**
   - Accepts user requests and optional working directory context.
2. **Skill Manager**
   - Loads SKILL.md files.
   - Maintains an index for keyword matching.
3. **Prompt Builder**
   - Combines base system prompt + tool descriptions + matched SKILL.md content.
4. **LLM Client (Adapter)**
   - Calls the selected chat-completion provider with tools enabled.
5. **Tool Executor**
   - Executes tool calls (MVP: only `bash_tool`).
   - Returns output and errors to the model loop.
6. **Safety Layer**
   - Command blacklist, path guardrails, confirmation on risky ops.
7. **CLI Adapter**
   - CLI for input, logs, and formatted output.
8. **Allowed Tools**
   - Respect `allowed-tools` in SKILL.md by blocking disallowed commands.

## Tooling Strategy
### MVP (recommended)
Only `bash_tool`:
```
{
  "name": "bash_tool",
  "description": "Execute any bash command on the system. Use standard Unix tools and installed CLIs.",
  "parameters": {
    "type": "object",
    "properties": {
      "command": {"type": "string"},
      "description": {"type": "string"}
    },
    "required": ["command"]
  }
}
```
Rationale:
- Simplest implementation
- Model already knows common shell workflows
- SKILL.md can teach best practices (e.g., `which <tool>` before use)

### Future Expansion
Add specialized tools if needed (read_file, write_file, str_replace) to improve safety, size limits, and validation.

## Data Flow (Example: "find some skills which can convert pdf to markdown")
1. **User Input**
   - "find some skills which can convert pdf to markdown"
2. **Skill Match**
   - Match `find_skills_plus` skill by keywords (find, skills, pdf, markdown).
3. **Prompt Build**
   - Base prompt + tool list + SKILL.md content (e.g., skill discovery workflow).
4. **LLM Call #1**
   - Model plans and emits tool call to search skills via `find_skills_plus`.
5. **Tool Execute #1**
   - Run the skill search script and return results.
6. **Final Response**
   - Model summarizes results and suggests next steps.

### Example Output (abbreviated)
```
anthropics/skills@pdf
└ https://skills.sh/anthropics/skills/pdf
This guide covers essential PDF processing operations using Python libraries and command-line tools. For advanced features, JavaScript libraries, and detailed examples, see reference.md. If you need to fill out a PDF form, read forms.md and follow its instructions.

davila7/claude-code-templates@markitdown
└ https://skills.sh/davila7/claude-code-templates/markitdown
MarkItDown is a Python tool developed by Microsoft for converting various file formats to Markdown. It's particularly useful for converting documents into LLM-friendly text format, as Markdown is token-efficient and well-understood by modern language models.

199-biotechnologies/claude-deep-research-skill@deep-research
└ https://skills.sh/199-biotechnologies/claude-deep-research-skill/deep-research
Purpose: Deliver citation-backed, verified research reports through 8-phase pipeline (Scope → Plan → Retrieve → Triangulate → Synthesize → Critique → Refine → Package) with source credibility scoring and progressive context management.

davila7/claude-code-templates@web-to-markdown
└ https://skills.sh/davila7/claude-code-templates/web-to-markdown
Convert web pages to clean Markdown by driving a locally installed browser (via web2md ).

aj-geddes/useful-ai-prompts@markdown-documentation
└ https://skills.sh/aj-geddes/useful-ai-prompts/markdown-documentation
Master markdown syntax and best practices for creating well-formatted, readable documentation using standard Markdown and GitHub Flavored Markdown (GFM).

gapmiss/obsidian-plugin-skill@obsidian
└ https://skills.sh/gapmiss/obsidian-plugin-skill/obsidian
You are assisting with Obsidian plugin development. Follow these comprehensive guidelines derived from the official Obsidian ESLint plugin rules, submission requirements, and best practices.
```

## MVP Responsibilities Split
- **LLM (AI)**: Task understanding, planning, tool selection.
- **Logic Code**: Skill loading, matching, prompt assembly, tool execution, safety checks.

## Provider Abstraction
Keep provider-specific details (auth, model names, response parsing, tool schema quirks) behind an adapter interface. The rest of the system should only depend on a provider-neutral `ChatClient` contract.

## UI and Logging
Follow the hexagonal UI and logging guide in `doc/ui-logging-guide.md` to keep core logic UI-agnostic and logging-driven.

## DeepSeek Defaults
- Model: DeepSeek V3 (`deepseek-chat`)
- JSON mode: `response_format: {"type": "json_object"}` with prompts that include the word "json"
- API key: `APIKEY_DEEPSEEK` environment variable

## Safety (MVP)
- Blocklist dangerous commands (rm -rf, dd, etc.).
- Path restrictions for destructive ops.
- Require confirmation for risky actions.
- Optional dry-run mode.

## Minimal Milestones
1. CLI + config
2. Skill Loader (SKILL.md only)
3. Prompt Builder
4. LLM API client adapter
5. Tool loop with `bash_tool`
6. Basic safety checks

## Open Questions
- Skills storage path: `~/.agent-skills-bot/skills/` vs XDG paths.
- Should the agent keep a global working directory or per-session context?
- How much conversation history to persist between sessions?

## Current Implementation Snapshot
- CLI default with command loop and multi-step tool loop (opt-out via `--no-loop`, limit via `--max-loop-count`).
- Skill discovery from `~/.agent-skills-bot/skills` plus built-in `bash-tool`.
- Two-pass routing with `deepseek-chat` and fallback to `deepseek-reasoner` on failure.
- MCP stdio support with auto-reconnect, notifications, and tool invocation (`mcp__server__tool`).
- References are listed and can be loaded into context (default yes).
