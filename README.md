# Code Quality Suite — Claude Code plugin

Two skills for auditing a codebase and its live deployment, with a polished HTML/PDF report.

- **code-audit** — runs six parallel reviewers (coding standards, duplication, logging, secrets, test quality, dependency freshness) and produces a color-coded HTML report with a health score, plain-language findings, clickable file links and an effort-sized fix plan. Can optionally run the passive live-site check and walk you through fixing issues.
- **live-site-audit** — a passive, read-only check of a running site (TLS, security headers, cookie flags, HTTP→HTTPS redirect). One GET per URL; no payloads, no probing. Only for sites you are authorized to test.

Both scripts use only the Python standard library — no install step.

## Install (for colleagues)

```
/plugin marketplace add <git-url-of-this-repo>
/plugin install code-quality-suite
```

Then run `/code-audit` in any project.

## Updating

Bump the version in `plugins/code-quality-suite/.claude-plugin/plugin.json`, commit and push. Colleagues re-run the marketplace update to get the new version.
