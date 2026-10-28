---
name: live-site-audit
description: Passively check a running website's transport and configuration health from the outside — TLS certificate validity and expiry, HTTPS redirect, security response headers (HSTS, CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy), Set-Cookie flags (Secure, HttpOnly, SameSite), and stack-disclosure headers. Use when the user wants to health-check or audit a live site, deployment or endpoint they are authorized to test, or review a URL's headers/TLS/cookies. Read-only: one ordinary GET per URL, no payloads, no fuzzing, no path probing, no credentials. NOT for scanning, exploitation, or testing sites the user does not control.
argument-hint: "[one or more URLs you are authorized to test]"
---

Run a **passive** external health and configuration check of one or more live URLs. This skill only inspects what a server volunteers in response to one ordinary request — the live-site equivalent of opening your browser's network tab. It never sends attack payloads, never fuzzes, never tries credentials, and never probes paths beyond the URLs given.

## Step 0: Confirm authorization and scope

Only proceed for sites the user owns or is explicitly authorized to test. If that is unclear from the conversation, ask once before running. Do not run against third-party sites "to see what happens."

Collect the target URLs from `$ARGUMENTS` or from the user's message. If the user names an environment ("staging", "the dev site") but no URL, ask for the exact URL(s).

## Step 1: Run the checker

```bash
python3 <this skill's directory>/scripts/check_site.py --json-out /tmp/live-site-<date>.json <url> [<url> ...]
```

The script uses only the Python standard library (no install step). For each URL it performs one GET, following redirects, and reports:

- **TLS** — certificate validates against trusted CAs, hostname match, days until expiry, negotiated protocol version (flags TLS 1.1 and older).
- **HTTPS redirect** — whether an `http://` URL is redirected to `https://`.
- **Security headers** — presence of HSTS, CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy.
- **Cookies** — Secure / HttpOnly / SameSite flags on each Set-Cookie.
- **Disclosure** — Server / X-Powered-By style headers that leak stack versions.

It prints a per-URL summary and finding list, and (with `--json-out`) writes structured JSON. Exit code is non-zero only if every URL was unreachable.

## Step 2: Report

Summarize in the chat: for each URL, the status, TLS protocol and cert expiry, and the count of high / medium / low findings, then list the high and medium findings with their plain-language why and fix. Keep it short; point to the JSON for the full detail.

If several URLs were checked, note any finding common to all of them (usually a platform-wide header or cookie setting worth fixing once at the load balancer or framework).

## Scope boundaries (do not cross without a separate, explicitly scoped request)

This skill is passive by design. It does **not**, and must not be extended here to:
- send crafted input, SQL/XSS/command-injection payloads, or oversized requests;
- enumerate or brute-force paths, parameters, usernames, or passwords;
- attempt authentication bypass, privilege escalation, or any form of gaining access;
- run load/stress/DoS traffic.

Active or intrusive testing (DAST scans, exploitation, credential testing) is a different activity that needs purpose-built tools run deliberately under a written authorization and rules of engagement — not a bundled skill feature. If the user asks for that, help them set up and interpret the appropriate dedicated tool for their specific authorized target; do not add offensive capability to this skill.
