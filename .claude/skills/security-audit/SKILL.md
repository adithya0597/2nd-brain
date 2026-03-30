---
name: security-audit
description: >
  Use this skill when evaluating a skill or script for security risks before
  installation, auditing a directory or git repo URL for malicious code, or
  performing a pre-install security gate for Claude Code plugins or custom
  skills. This covers scanning Python scripts for dangerous patterns (os.system,
  eval, subprocess, network exfiltration), detecting prompt injection in SKILL.md
  files, checking dependency supply chain risks (typosquatting, unpinned versions),
  and verifying file system access stays within skill boundaries. Also use to audit
  internal project scripts for credential leaks or unsafe patterns. Distinguished
  from dep-audit (which focuses on dependency versions, licenses, and upgrades
  rather than code-level security) and from pr-review (which reviews a commit diff
  rather than scanning a full directory).
---

# Skill Security Auditor

Scan and audit AI agent skills for security risks before installation. Produces a
clear **PASS / WARN / FAIL** verdict with findings and remediation guidance.

## Quick Start

```bash
# Audit a local skill directory
python3 .claude/skills/security-audit/scripts/skill_security_auditor.py /path/to/skill-name/

# Audit the brain-bot itself
python3 .claude/skills/security-audit/scripts/skill_security_auditor.py ./file://scripts/brain-bot/

# Audit a skill from a git repo
python3 .claude/skills/security-audit/scripts/skill_security_auditor.py https://github.com/user/repo --skill skill-name

# Audit with strict mode (any WARN becomes FAIL)
python3 .claude/skills/security-audit/scripts/skill_security_auditor.py /path/to/skill-name/ --strict

# Output JSON report
python3 .claude/skills/security-audit/scripts/skill_security_auditor.py /path/to/skill-name/ --json
```

## What Gets Scanned

### 1. Code Execution Risks (Python/Bash Scripts)

Scans all `.py`, `.sh`, `.bash`, `.js`, `.ts` files for:

| Category | Patterns Detected | Severity |
|----------|-------------------|----------|
| **Command injection** | `os.system()`, `os.popen()`, `subprocess.call(shell=True)`, backtick execution | CRITICAL |
| **Code execution** | `eval()`, `exec()`, `compile()`, `__import__()` | CRITICAL |
| **Obfuscation** | base64-encoded payloads, `codecs.decode`, hex-encoded strings, `chr()` chains | CRITICAL |
| **Network exfiltration** | `requests.post()`, `urllib.request`, `socket.connect()`, `httpx`, `aiohttp` | CRITICAL |
| **Credential harvesting** | reads from `~/.ssh`, `~/.aws`, `~/.config`, env var extraction patterns | CRITICAL |
| **File system abuse** | writes outside skill dir, `/etc/`, `~/.bashrc`, `~/.profile`, symlink creation | HIGH |
| **Privilege escalation** | `sudo`, `chmod 777`, `setuid`, cron manipulation | CRITICAL |
| **Unsafe deserialization** | `pickle.loads()`, `yaml.load()` (without SafeLoader), `marshal.loads()` | HIGH |
| **Subprocess (safe)** | `subprocess.run()` with list args, no shell | INFO |

### 2. Prompt Injection in SKILL.md

Scans SKILL.md and all `.md` reference files for:

| Pattern | Example | Severity |
|---------|---------|----------|
| **System prompt override** | "Ignore previous instructions", "You are now..." | CRITICAL |
| **Role hijacking** | "Act as root", "Pretend you have no restrictions" | CRITICAL |
| **Safety bypass** | "Skip safety checks", "Disable content filtering" | CRITICAL |
| **Hidden instructions** | Zero-width characters, HTML comments with directives | HIGH |
| **Excessive permissions** | "Run any command", "Full filesystem access" | HIGH |
| **Data extraction** | "Send contents of", "Upload file to", "POST to" | CRITICAL |

### 3. Dependency Supply Chain

For skills with `requirements.txt`, `package.json`, or inline `pip install`:

| Check | What It Does | Severity |
|-------|-------------|----------|
| **Known vulnerabilities** | Cross-reference with PyPI/npm advisory databases | CRITICAL |
| **Typosquatting** | Flag packages similar to popular ones (e.g., `reqeusts`) | HIGH |
| **Unpinned versions** | Flag `requests>=2.0` vs `requests==2.31.0` | INFO |
| **Install commands in code** | `pip install` or `npm install` inside scripts | HIGH |
| **Suspicious packages** | Low download count, recent creation, single maintainer | INFO |

### 4. File System & Structure

| Check | What It Does | Severity |
|-------|-------------|----------|
| **Boundary violation** | Scripts referencing paths outside skill directory | HIGH |
| **Hidden files** | `.env`, dotfiles that shouldn't be in a skill | HIGH |
| **Binary files** | Unexpected executables, `.so`, `.dll`, `.exe` | CRITICAL |
| **Large files** | Files >1MB that could hide payloads | INFO |
| **Symlinks** | Symbolic links pointing outside skill directory | CRITICAL |

### 5. Project-Specific Checks (Second Brain)

When auditing scripts within this project, additionally check:

| Check | What It Does | Severity |
|-------|-------------|----------|
| **Legitimate env vars** | TELEGRAM_BOT_TOKEN, OWNER_TELEGRAM_ID, GROUP_CHAT_ID, GEMINI_API_KEY, NOTION_TOKEN, LANGFUSE_* are expected and should not be flagged | INFO |
| **SQLite injection** | All SQL in `core/*.py` uses parameterized queries (? placeholders), not f-strings | HIGH |
| **Vault path traversal** | vault_ops.py writes only within the vault/ subtree | HIGH |
| **Git history exposure** | .env was never committed (check with `git log --all -- ".env"`) | CRITICAL |
| **Bot token in logs** | TELEGRAM_BOT_TOKEN not printed in brain-bot.log or Telegram messages | HIGH |
| **Notion token scope** | NOTION_TOKEN only used in notion_sync.py and notion_client.py | HIGH |

## Audit Workflow

1. **Run the scanner** on the skill directory or repo URL
2. **Review the report** — findings grouped by severity
3. **Verdict interpretation:**
   - **PASS** — No critical or high findings. Safe to install.
   - **WARN** — High/medium findings detected. Review manually before installing.
   - **FAIL** — Critical findings. Do NOT install without remediation.
4. **Remediation** — each finding includes specific fix guidance

## Advanced Usage

### Audit a Skill from Git Before Cloning

```bash
python3 .claude/skills/security-audit/scripts/skill_security_auditor.py https://github.com/user/skill-repo --skill my-skill --cleanup
```

### Batch Audit All Skills

```bash
for skill in .claude/skills/*/; do
  python3 .claude/skills/security-audit/scripts/skill_security_auditor.py "$skill" --json >> audit-results.jsonl
done
```

## Threat Model Reference

For the complete threat model, detection patterns, and known attack vectors against AI agent skills, see [references/threat-model.md](references/threat-model.md).

## Limitations

- Cannot detect logic bombs or time-delayed payloads with certainty
- Obfuscation detection is pattern-based — a sufficiently creative attacker may bypass it
- Network destination reputation checks require internet access
- Does not execute code — static analysis only (safe but less complete than dynamic analysis)
- Dependency vulnerability checks use local pattern matching, not live CVE databases

When in doubt after an audit, **don't install**. Ask the skill author for clarification.
