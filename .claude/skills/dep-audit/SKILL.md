---
name: dep-audit
description: >
  Use this skill when auditing project dependencies for security vulnerabilities,
  license compliance issues, outdated versions, or upgrade planning — any request
  involving "are my dependencies safe?" or "what needs updating?" This covers
  vulnerability scanning against built-in CVE patterns, license compatibility
  checking across permissive/copyleft/proprietary licenses, outdated dependency
  detection with semver analysis, and upgrade path planning with breaking change
  risk assessment. Supports Python (requirements.txt, pyproject.toml), Node.js
  (package.json), Go (go.mod), Rust, Ruby, Java, PHP, and C#. Distinguished from
  security-audit (which scans code for malicious patterns, not dependency versions)
  and from pr-review (which checks a diff for dependency-related risks but does
  not do comprehensive auditing).
---

# Dependency Auditor

Comprehensive dependency analysis: vulnerabilities, licenses, outdated packages, and upgrade planning.

## Steps

### 1. Identify Dependency Files

Scan the project for dependency manifests:

```bash
python3 .claude/skills/dep-audit/scripts/dep_scanner.py /path/to/project
```

Supported files: requirements.txt, pyproject.toml, Pipfile.lock, poetry.lock, package.json, package-lock.json, yarn.lock, go.mod, Cargo.toml, Gemfile, pom.xml, composer.json, packages.config

### 2. Run Vulnerability Scan

```bash
# Scan for known CVEs and security issues
python3 .claude/skills/dep-audit/scripts/dep_scanner.py ./file://scripts/brain-bot/

# JSON output for automation
python3 .claude/skills/dep-audit/scripts/dep_scanner.py ./file://scripts/brain-bot/ --format json

# Fail on high-severity findings (for CI gates)
python3 .claude/skills/dep-audit/scripts/dep_scanner.py ./file://scripts/brain-bot/ --fail-on-high
```

**What it checks:**
- Known CVE patterns (500+ built-in)
- CVSS severity scoring (Critical/High/Medium/Low)
- Typosquatting detection (e.g., `reqeusts` vs `requests`)
- Unpinned versions (e.g., `>=2.0` vs `==2.31.0`)
- Runtime install commands in scripts

### 3. Check License Compliance

```bash
# Check licenses with strict policy
python3 .claude/skills/dep-audit/scripts/license_checker.py ./file://scripts/brain-bot/ --policy strict

# Permissive policy (allow weak copyleft)
python3 .claude/skills/dep-audit/scripts/license_checker.py ./file://scripts/brain-bot/ --policy permissive
```

**License categories:**

| Category | Examples | Risk |
|----------|----------|------|
| Permissive | MIT, Apache 2.0, BSD | Low |
| Weak Copyleft | LGPL, MPL | Medium |
| Strong Copyleft | GPL, AGPL | High |
| Proprietary | Commercial | Critical |
| Unknown | Missing license | Critical |

### 4. Plan Upgrades

```bash
# Generate upgrade plan from scan results
python3 .claude/skills/dep-audit/scripts/upgrade_planner.py deps.json --risk-threshold medium

# With timeline
python3 .claude/skills/dep-audit/scripts/upgrade_planner.py deps.json --timeline 30
```

**Upgrade priority:**
1. Security patches (Critical/High CVEs) — immediate
2. Bug fixes — next sprint
3. Feature updates (minor versions) — planned
4. Major version upgrades — scheduled with testing

### 5. Review and Prioritize

After scanning, review findings by severity:
- **Critical**: Known exploited CVEs, license violations — fix immediately
- **High**: Unpinned versions with known vulns, GPL contamination — fix this sprint
- **Medium**: Outdated minor versions, maintenance concerns — plan upgrade
- **Low/Info**: Unpinned versions, minor recommendations — track

### 6. Apply and Verify

```bash
# Update requirements.txt with pinned versions
# Run full test suite after each update
cd ./file://scripts/brain-bot && python -m pytest -q

# Verify no regressions
python -m pytest tests/ -x --tb=short
```

## Second Brain Key Dependencies

Dependencies to watch closely in `file://scripts/brain-bot/requirements.txt`:

| Package | Why It Matters |
|---------|---------------|
| `python-telegram-bot` | Core bot framework — major versions break handlers |
| `sentence-transformers` | Embedding model — version changes affect vector compatibility |
| `sqlite-vec` | Vector search — tied to SQLite version |
| `anthropic` | Claude API — breaking changes in SDK |
| `notion-client` | Notion sync — API version changes |
| `google-genai` | Gemini fallback — new SDK |
| `faster-whisper` | Voice transcription — model compatibility |
| `langfuse` | Observability — optional but version-sensitive |

## Technical Architecture

| Tool | Script | Purpose |
|------|--------|---------|
| Scanner | `scripts/dep_scanner.py` | Multi-ecosystem vulnerability detection |
| License Checker | `scripts/license_checker.py` | License classification and conflict detection |
| Upgrade Planner | `scripts/upgrade_planner.py` | Semver analysis and upgrade path planning |

All scripts are stdlib-only Python (no external dependencies required).

## Reference Documentation

- `references/vulnerability_assessment_guide.md` — CVSS scoring, CWE types, risk methodology
- `references/license_compatibility_matrix.md` — License compatibility table, conflict scenarios
- `references/dependency_management_best_practices.md` — Governance, evaluation criteria, policy templates

## Best Practices

1. **Pin exact versions** — `==2.31.0` not `>=2.0`
2. **Scan on every dependency change** — before committing updated requirements.txt
3. **Security patches first** — always prioritize CVE fixes over feature upgrades
4. **Test after each upgrade** — run full pytest suite, verify bot starts cleanly
5. **Review licenses** — especially for new dependencies before adding
