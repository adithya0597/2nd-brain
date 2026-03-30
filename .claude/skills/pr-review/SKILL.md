---
name: pr-review
description: >
  Use this skill when reviewing code changes before committing to main — any
  request to review a diff, audit recent changes, or validate that modifications
  follow project conventions. This includes blast radius analysis (which modules
  import the changed code), security scanning (SQL injection in SQLite queries,
  credential exposure, unsafe eval), test coverage delta with pytest, breaking
  change detection (DB schema migrations, config key removals, ICOR hierarchy
  changes), and performance impact assessment (N+1 queries, unbounded loops,
  embedding recomputation). Produces a structured review with MUST FIX, SHOULD
  FIX, and SUGGESTIONS tiers plus a project-specific checklist. Distinguished
  from security-audit (which scans an entire directory for installation safety,
  not a commit diff) and from the code-simplifier agent (which refactors for
  clarity, not correctness or security).
---

# Code Review for Second Brain

Structured code review for changes before committing to main. Goes beyond style — performs blast radius analysis, security scanning, breaking change detection, and test coverage assessment.

## Steps

### 1. Fetch the Diff

```bash
# View what changed
git diff HEAD~1
git diff --name-only HEAD~1

# For multi-commit review
git diff main...HEAD
git log --oneline main..HEAD

# Save diff for analysis
git diff HEAD~1 > /tmp/review.diff
```

### 2. Blast Radius Analysis

For each changed file, identify who depends on it:

```bash
# Find all files importing a changed module
grep -r "from changed_module import\|import changed_module" ./file://scripts/brain-bot/ --include="*.py" -l
```

**Second Brain blast radius rules:**
- `core/classifier.py` — used by 8+ command handlers via context_loader
- `core/vault_indexer.py` — boot sequence + post-write hooks + graph_ops
- `core/embedding_store.py` — search, chunk_embedder, classifier
- `core/context_loader.py` — every command handler
- `core/ai_client.py` — commands.py + scheduled.py
- `config.py` — imported by every module
- `core/notion_sync.py` — scheduled sync + /sync command

**Blast radius severity:**

| Level | Examples |
|-------|---------|
| CRITICAL | core/ modules, config.py, app.py boot sequence, migrate-db.py |
| HIGH | handlers/commands.py, handlers/scheduled.py, .claude/commands/brain/*.md |
| MEDIUM | Single handler, single test file, formatter |
| LOW | Documentation, vault template, .env.example |

### 3. Security Scan

```bash
DIFF=/tmp/review.diff

# SQL injection — f-string SQL (should use ? placeholders)
grep -n 'f".*SELECT\|f".*INSERT\|f".*UPDATE\|f".*DELETE' $DIFF

# Hardcoded secrets or tokens
grep -nE "(password|secret|api_key|token|private_key)\s*=\s*['\"][^'\"]{8,}" $DIFF

# eval/exec in Python
grep -nE "\beval\(|\bexec\(" $DIFF

# Unsafe subprocess
grep -n "subprocess.call.*shell=True\|subprocess.Popen.*shell=True" $DIFF

# Unsafe deserialization
grep -nE "pickle\.loads|yaml\.load\(" $DIFF | grep -v "SafeLoader\|safe_load"

# Credential in logs or messages
grep -n "TELEGRAM_BOT_TOKEN\|NOTION_TOKEN\|GEMINI_API_KEY" $DIFF | grep -E "print\(|log\.|send_message"

# os.system or os.popen
grep -nE "os\.system\(|os\.popen\(" $DIFF
```

### 4. Test Coverage Delta

```bash
# Count source vs test files changed
CHANGED_SRC=$(git diff --name-only HEAD~1 | grep -v "tests/" | grep "\.py$")
CHANGED_TESTS=$(git diff --name-only HEAD~1 | grep "tests/" | grep "\.py$")

echo "Source files changed: $(echo "$CHANGED_SRC" | grep -c .)"
echo "Test files changed:   $(echo "$CHANGED_TESTS" | grep -c .)"

# Run coverage
cd ./file://scripts/brain-bot && python -m pytest --cov --cov-report=term-missing 2>/dev/null | tail -20
```

**Coverage rules:**
- New public function in `core/` — requires unit test in `tests/test_*.py`
- New handler in `handlers/` — requires integration test
- Deleted tests without deleted code — flag
- Coverage drop >5% — block merge

### 5. Breaking Change Detection

**SQLite Schema:**
```bash
# Check for migration changes
git diff HEAD~1 -- ./file://scripts/migrate-db.py

# Destructive operations
grep -E "DROP TABLE|DROP COLUMN|ALTER.*NOT NULL" /tmp/review.diff

# New migration steps — verify step number is sequential
grep "Step [0-9]" ./file://scripts/migrate-db.py | tail -5
```

**Config Changes:**
```bash
# New env vars in config.py
grep "^+" /tmp/review.diff | grep -oE "os\.environ\[.*?\]\|os\.environ\.get\(.*?\)" | sort -u

# Check .env.example is updated if new env vars added
git diff HEAD~1 -- .env.example
```

**ICOR & Notion:**
- Changes to ICOR hierarchy (config.py DIMENSION_* constants) — migration step required
- Changes to notion_sync.py push methods — verify outbox idempotency
- Changes to Notion collection IDs — update CLAUDE.md

**Prompt Files:**
- Changes to `.claude/commands/brain/*.md` — estimate token count (warn if >4000)
- Changes to SKILL.md files — verify frontmatter format

### 6. Performance Impact

```bash
# N+1 patterns: DB calls inside loops
grep -n "execute\|fetchall\|fetchone" /tmp/review.diff | grep "^+"

# Unbounded queries
grep -n "SELECT.*FROM" /tmp/review.diff | grep -v "LIMIT" | grep "^+"

# Embedding recomputation triggers
git diff HEAD~1 -- ./file://scripts/brain-bot/core/embedding_store.py ./file://scripts/brain-bot/core/chunk_embedder.py

# Large file operations without streaming
grep -n "read()\|readlines()" /tmp/review.diff | grep "^+"
```

### 7. Project-Specific Checks

- [ ] **conftest.py updated**: If new config attributes added to `config.py`, `_ensure_config_defaults()` in `tests/conftest.py` must be updated
- [ ] **requirements.txt pinned**: New dependencies use exact versions (`==`), not ranges (`>=`)
- [ ] **Vault frontmatter**: New vault files have proper YAML frontmatter (type, date, etc.)
- [ ] **CLAUDE.md current**: If architecture changed, update relevant CLAUDE.md sections
- [ ] **Post-write hooks**: If new vault write function added to `vault_ops.py`, `_on_vault_write` hook must be wired

## Review Checklist

```markdown
### Scope & Context
- [ ] Changes are focused (no scope creep)
- [ ] Commit message explains WHY, not just WHAT

### Blast Radius
- [ ] All modules importing changed code identified
- [ ] No unintended side effects on scheduled jobs
- [ ] New env vars documented in .env.example

### Security
- [ ] No hardcoded secrets or API keys
- [ ] SQL uses parameterized queries (? placeholders)
- [ ] No tokens in log output or Telegram messages
- [ ] No eval/exec or unsafe subprocess
- [ ] No pickle.loads or yaml.load without SafeLoader

### Testing
- [ ] New core/ functions have unit tests
- [ ] New handlers have integration tests
- [ ] conftest.py _ensure_config_defaults() updated if needed
- [ ] 826+ tests still pass

### Breaking Changes
- [ ] No SQLite schema changes without migration step
- [ ] No config.py env vars without .env.example update
- [ ] No ICOR changes without config + migration update
- [ ] Notion sync uses outbox pattern (not inline push)

### Performance
- [ ] No N+1 query patterns (DB calls in loops)
- [ ] No unbounded SELECT without LIMIT
- [ ] No full vault re-embedding triggered unnecessarily
- [ ] New SQLite queries have appropriate indexes

### Code Quality
- [ ] No dead code or unused imports
- [ ] Error handling present (no bare except:)
- [ ] Consistent with existing patterns
```

## Output Format

```
## Code Review: [Description]

Blast Radius: [CRITICAL/HIGH/MEDIUM/LOW] — [reason]
Security: [N findings]
Tests: [coverage delta]
Breaking Changes: [None/list]

--- MUST FIX (Blocking) ---
[numbered findings with file:line, risk, and fix]

--- SHOULD FIX (Non-blocking) ---
[numbered findings]

--- SUGGESTIONS ---
[numbered suggestions]

--- LOOKS GOOD ---
[positive observations]
```

## Common Pitfalls

- **Reviewing style over substance** — let ruff handle style; focus on logic, security, correctness
- **Missing blast radius** — a 5-line change in core/classifier.py can break 8 command handlers
- **Approving untested code** — always verify new core/ functions have tests
- **Ignoring migration risk** — NOT NULL additions need defaults or two-phase migration
- **Skipping conftest check** — missing _ensure_config_defaults() causes cascading test failures
