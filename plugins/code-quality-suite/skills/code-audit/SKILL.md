---
name: code-audit
description: Run a full code quality audit of a project (or one subdirectory) with up to 9 parallel agents covering coding standards, duplication, logging/debug leftovers, secrets and env handling, test quality/coverage, dependency freshness/vulnerabilities, code-level security vulnerabilities (OWASP Top 10), exploitable loopholes (attacker's-eye review of entry points and business logic) and a security-controls gap analysis (OWASP ASVS), then produce a professional, color-coded HTML report in plain language (health score, findings with clickable file paths, effort-sized fix plan). Use this whenever the user asks to audit, review, health-check, or assess the quality of a codebase, module or folder, asks "what's wrong with this code", wants to find tech debt, duplicated code, leftover console.logs, hardcoded secrets, untested files or outdated/vulnerable packages, asks for a vulnerability assessment, security review, gap analysis, attack-surface review or "how could someone hack this", or is preparing for a SonarQube/quality gate, refactor sprint or handover, even if they don't say "audit". Not for reviewing a single diff or PR.
argument-hint: "[optional path to scope the audit]"
---

Run a comprehensive code quality audit of this project. If the user provided a path argument, scope the audit to that subdirectory only: `$ARGUMENTS`

If `$ARGUMENTS` is empty but the user named a folder, module or feature in their message, use that as the scope instead.

## Step 0: Talk to the user first (intake)

Before running anything, act like an assistant setting up the job. Ask the user the questions below with the `AskUserQuestion` tool — but **skip any question the user already answered** in their message or in `$ARGUMENTS` (for example, if they already said "audit the pim folder and test the live site at https://...", don't ask about scope or the live site again). If everything is already specified, skip Step 0 and proceed.

Batch these into one `AskUserQuestion` call:

1. **Live site check** — "Do you also want a passive check of the running site?" (Yes / No). If Yes and no URL was given, ask for the exact URL in a follow-up, and confirm it is a site the user owns or is authorized to test. This runs the read-only `live-site-audit` check (one GET per URL: TLS, security headers, cookies, HTTP→HTTPS redirect — no payloads, no probing). Decline politely if authorization is unclear.
2. **Where to save the report** — offer the default `audit-reports/` plus "another folder". Store the answer as `REPORT_DIR` (default `audit-reports/`); create it if missing.
3. **Scope** — only if still unknown after `$ARGUMENTS` and the message: whole project or a specific folder.
4. **Audit type** — "Which checks should I run?" (Full audit: quality + security, all 9 agents (Recommended) / Security only: agents 4, 6, 7, 8, 9 / Code quality only: agents 1-6). Store as `AUDIT_TYPE`; default Full.
5. **Fix issues afterward** — "After the report, do you want me to fix some of the issues?" (Yes, walk me through it / No, report only). If Yes, do Step 7 after the report; if No, stop after Step 6.

Keep it brief and helpful, not a long questionnaire. Remember the answers — they drive the scope and which agents run (Step 2), the live-site sub-step, where files are written (Steps 4–5), and whether Step 7 runs.

### Live-site sub-step (only if the user asked for it)

Run the passive checker and keep its output for the report:

```bash
python3 <this skill's directory>/scripts/check_site.py --json-out <REPORT_DIR>/live-site-<YYYY-MM-DD>.json <url> [<url> ...]
```

Turn its results into a `live_site` block in the report JSON (see Step 4) and add any real problem it found (e.g. a missing security header, an expiring certificate) as a Security finding so it shows up in the findings list too.

## Step 1: Auto-detect project context

Read the project root to determine language and framework. Check for files like `package.json`, `Cargo.toml`, `pyproject.toml`, `go.mod`, `pom.xml`, `build.gradle`, `*.sln`, `Gemfile`, or similar. Also check for `tsconfig.json`, `.eslintrc*`, `eslint.config.*`, `CLAUDE.md`, and any linting/formatting config. Identify:
- Primary language(s) and framework(s)
- Test framework and test directory convention
- Source directory convention
- Any project-specific coding standards from CLAUDE.md or linter configs

Store this as a short context string (2-3 sentences). You will pass this to each subagent.

## Step 2: Launch the parallel audit agents

Launch every agent selected by `AUDIT_TYPE` (Full: 1-9, Security only: 4, 6, 7, 8, 9, Code quality only: 1-6) in a single message so they run in parallel; launching them one by one makes the audit take several times as long. Agents 1-5 and 7-9 use `subagent_type: "Explore"`, because they only read code. Agent 6 uses `subagent_type: "general-purpose"`, because it needs Bash to run audit CLI tools. Each agent receives the project context string from Step 1.

**Security agents (7-9) are read-only code reviewers.** They must not send requests to any live system, run exploits, or write working attack payloads or proof-of-concept exploit code. Attack scenarios are described in plain words (who, what entry point, what they gain), which is enough for the team to understand and fix the issue. If a live-site check was requested, that stays the passive `live-site-audit` run from Step 0, nothing more.

If a scope was set (from `$ARGUMENTS` or from the user's message), tell each agent to restrict its search to that path. Otherwise, agents search the full project source (excluding node_modules, dist, build, vendor, .git, and similar output directories).

**Output constraint for every agent**: return only a structured bullet list of findings. Nine agents' worth of prose would flood your context and make deduplication in Step 3 unreliable, so the fixed format matters. Each finding must follow this exact format:
```
- [HIGH|MEDIUM|LOW] <short description> — <file:line> (and <file:line> if comparing two locations) | why: <one plain sentence on the consequence> | fix: <one sentence on the concrete change>
```
The `why` and `fix` parts feed the plain-language report in Step 4, so keep them concrete.
Maximum 15 findings per agent. No prose, no preamble, no summary paragraph — just the bullet list. If no issues found, return `- No issues found.`

Agents 7 and 8 append extra fields to each bullet (`| owasp: ... | cwe: ... | exploit: easy|moderate|hard | scenario: ...`), and Agent 9 returns a control table instead of findings. Their prompts below give the exact format.

### Agent 1: Coding Standards & Consistency

```
You are auditing a <context>.

Check that the codebase follows consistent coding standards and patterns. Look for:

1. NAMING: Inconsistent naming conventions — mixing camelCase/snake_case/PascalCase where the project uses one style. Check variable names, function names, file names, and export names.
2. PATTERNS: Inconsistent application of project patterns — if the project uses a specific pattern (e.g., singleton init, error handling, module structure), find places that deviate from that pattern without justification.
3. ERROR HANDLING: Inconsistent error handling — some functions throw, some return null, some swallow errors silently. Flag functions that handle errors differently from the dominant pattern.
4. STYLE: Inconsistent code style within the same project — e.g., mixing async/await with .then() chains, mixing arrow functions with function declarations for the same purpose, inconsistent import ordering.

Use Glob to find source files, Read to examine them, Grep to find patterns.
Return findings as: - [HIGH|MEDIUM|LOW] description — file:line (and file:line) | why: ... | fix: ...
Max 15 findings. No prose.
```

### Agent 2: Code Duplication

```
You are auditing a <context>.

Scan source files (NOT test files) for duplication and repeated patterns. Look for:

1. NEAR-IDENTICAL FUNCTIONS: Functions across different files that do essentially the same thing with minor variations (different variable names, slight parameter differences). Compare function signatures and bodies.
2. COPY-PASTED BLOCKS: 3+ lines of similar code appearing in multiple places that could be extracted into a shared helper.
3. REPEATED LOGIC: The same pattern of API calls, data transformations, or error handling repeated across files. E.g., the same try/catch/log pattern, the same data formatting logic, the same validation sequence.
4. DUPLICATED CONSTANTS: Magic strings or numbers repeated in multiple files instead of being defined in one place.

Use Glob to find source files, Read to examine them, Grep to find repeated string literals and similar function names. Focus on the most impactful duplications first.
Return findings as: - [HIGH|MEDIUM|LOW] description — file:line (and file:line) | why: ... | fix: ...
Max 15 findings. No prose.
```

### Agent 3: Logging Hygiene & Debug Artifacts

```
You are auditing a <context>.

Check for improper logging practices and leftover debug artifacts. Look for:

1. RAW CONSOLE CALLS: Any use of console.log, console.warn, console.error, console.info, console.debug, or language equivalents (print, println, fmt.Println, etc.) in production source code. These should use a proper structured logging library/service instead. Flag every instance.
2. DEBUG LEFTOVERS: Temporary debugging code left in — commented-out console.log/print statements, TODO/FIXME/HACK/XXX comments that reference debugging, temporary variables only used for logging.
3. SENSITIVE DATA IN LOGS: Log statements that might output tokens, passwords, API keys, user data, or full request/response bodies. Check what variables are being passed to log calls.
4. INCONSISTENT LOG LEVELS: If the project does have a logger, check that log levels are used appropriately — errors logged as info, info logged as debug, etc.

Use Grep to search for console.log, console.warn, console.error, console.info, console.debug, print, println, and similar patterns. Read the surrounding context to assess severity.
Return findings as: - [HIGH|MEDIUM|LOW] description — file:line | why: ... | fix: ...
Max 15 findings. No prose.
```

### Agent 4: Security — Secrets & Environment Handling

```
You are auditing a <context>.

Check for security issues related to secrets, environment variables, and sensitive data handling. Look for:

1. HARDCODED SECRETS: Any hardcoded API keys, tokens, passwords, connection strings, or credentials in source code. Check for strings that look like tokens (long alphanumeric strings), URLs with embedded credentials, and variables named key/secret/token/password with literal values.
2. ENV VALIDATION: Environment variables accessed directly (process.env.X, os.environ, etc.) without validation or type checking. They should go through a validated config layer, not be read ad-hoc throughout the codebase.
3. GITIGNORE GAPS: Check .gitignore for missing entries — .env files, credential files (*.pem, *.key, service-account.json), data directories with potentially sensitive content, IDE configs that may contain project-specific secrets.
4. SECRET EXPOSURE: Secrets that could leak through error messages, stack traces, API responses, or log output. Check error handlers and catch blocks for what they expose.
5. COMMITTED SECRETS: Check if any .env, credential, or key files exist in the repo (not just gitignored but actually present in tracked files).

Use Glob to find config files, .env files, credential files. Grep for patterns like hardcoded tokens, process.env, os.environ. Read .gitignore and compare against actual files.
Return findings as: - [HIGH|MEDIUM|LOW] description — file:line | why: ... | fix: ...
Max 15 findings. No prose.
```

### Agent 5: Test Quality & Coverage

```
You are auditing a <context>.

Evaluate test quality, coverage gaps, and superfluous tests. Look for:

1. COVERAGE GAPS: Source files or modules that have NO corresponding test file. List each untested source file. Cross-reference by checking if each source file's exports are imported in any test file.
2. SUPERFLUOUS TESTS: Tests that don't actually assert anything meaningful — tests that only check truthiness, tests that are essentially duplicates of other tests with trivially different inputs, tests that mock so heavily they only test the mocks, tests that test language/framework behavior rather than application logic.
3. DUPLICATED TEST SETUP: Identical or near-identical beforeEach/beforeAll/setup blocks across multiple test files that should be extracted into shared test helpers. Repeated mock definitions that could be centralized.
4. FRAGILE TESTS: Tests tightly coupled to implementation details — testing private internals, asserting on exact string output that will break on formatting changes, testing mock call counts instead of behavior.
5. MISSING EDGE CASES: Test files that only test the happy path for functions that have obvious error/edge cases (null inputs, empty arrays, network failures, etc.).

Use Glob to find all test files and all source files. Read test files to assess quality. Grep to check which source exports are referenced in test files.
Return findings as: - [HIGH|MEDIUM|LOW] description — file:line | why: ... | fix: ...
Max 15 findings. No prose.
```

### Agent 6: Dependency Freshness & Security

Use `subagent_type: "general-purpose"` for this one, not "Explore": it has to run `npm audit` and similar tools, and Explore agents have no Bash.

```
You are auditing a <context>.

Check dependency freshness, security vulnerabilities, and lockfile health.
The project context tells you which ecosystems are in use. For each detected
ecosystem, run the appropriate checks:

**For Node.js (package.json detected):**
1. Run `npm audit --json 2>/dev/null` — flag critical and high vulnerabilities as HIGH, moderate as MEDIUM
2. Run `npm outdated --json 2>/dev/null` — flag packages 2+ major versions behind as MEDIUM, 1 major as LOW, minor/patch as LOW
3. Verify package-lock.json exists and is committed. If missing, flag as MEDIUM.

**For Python (pyproject.toml or requirements.txt detected):**
1. Run `pip-audit --format=json 2>/dev/null` — flag critical/high as HIGH, moderate as MEDIUM
2. Run `pip list --outdated --format=json 2>/dev/null` — flag packages 2+ major versions behind as MEDIUM, others as LOW
3. Verify lock file (poetry.lock, requirements.txt with pinned versions) exists. If missing, flag as MEDIUM.

**For Rust (Cargo.toml detected):**
1. Run `cargo audit --json 2>/dev/null` — flag critical/high as HIGH, moderate as MEDIUM
2. Run `cargo outdated --root-deps-only 2>/dev/null` — flag 2+ major versions behind as MEDIUM, others as LOW
3. Verify Cargo.lock exists and is committed. If missing, flag as MEDIUM.

**For Go (go.mod detected):**
1. Run `govulncheck ./... 2>/dev/null` — flag vulnerabilities as HIGH
2. Run `go list -m -u all 2>/dev/null` — flag major updates as MEDIUM, minor/patch as LOW
3. Verify go.sum exists and is committed. If missing, flag as MEDIUM.

If a CLI tool is not installed or fails, note it as:
- [LOW] <tool> not available — unable to check <ecosystem> <check type>

Do NOT flag devDependencies outdated versions as MEDIUM or HIGH — cap at LOW.
Do NOT flag pre-release or alpha/beta versions as outdated.
Prioritize HIGH and MEDIUM findings first. Only include LOW (minor/patch outdated) findings if you have remaining slots in the 15-finding cap.

Return findings as: - [HIGH|MEDIUM|LOW] description — package@version (current -> latest) | why: ... | fix: ...
For lockfile or tooling issues, use a descriptive identifier instead of package@version.
Max 15 findings. No prose.
```

### Agent 7: Security Vulnerabilities (code-level, OWASP Top 10)

```
You are auditing a <context>.

You are a defensive security reviewer reading the source code. Do NOT send requests to any running system, run exploits, or write working payloads or proof-of-concept code — describe issues in plain words only.

Find code-level vulnerabilities. Trace untrusted input (URL/query params, route params, request bodies, headers, cookies, form fields, file uploads, CMS/API content, postMessage, localStorage) to dangerous sinks. Look for:

1. INJECTION (A03): SQL/NoSQL/ORM raw queries built with string concatenation, shell/exec/spawn with user input, template injection, LDAP/XPath, header/CRLF injection, regex built from user input (ReDoS).
2. XSS (A03): innerHTML/outerHTML/document.write/insertAdjacentHTML, dangerouslySetInnerHTML, v-html, Angular bypassSecurityTrust*/custom "no-sanitize" pipes, [innerHTML] bound to API or CMS content, unescaped server-side templates, JSON embedded in <script> without escaping, javascript: URLs in href bindings.
3. BROKEN ACCESS CONTROL (A01): endpoints or server routes with no auth check, authorization done only in the client (route guards, hidden buttons) with the API trusting the caller, IDs taken from the request without an ownership check (IDOR), admin/debug/test routes reachable publicly, CORS reflecting arbitrary origins or allowing credentials with wildcards.
4. SSRF and OPEN REDIRECT (A10/A01): server-side fetch/http/axios to a URL or host built from request data, proxy endpoints, redirects to a user-supplied URL or Host/X-Forwarded-Host header without an allow-list.
5. PATH TRAVERSAL and FILE HANDLING: file paths built from request data, unsafe file upload (no type/size check, stored in a web-served folder, original filename trusted), zip extraction without path checks.
6. AUTH and SESSION (A07): tokens stored in localStorage, JWT decoded without verification or with alg none, weak or missing CSRF protection on cookie-authenticated state-changing requests, session not cleared on logout, password reset or login without rate limits, predictable tokens (Math.random for security values).
7. CRYPTO and DATA (A02/A08): weak hashing (md5/sha1 for passwords), hardcoded IV/salt, disabled TLS verification (rejectUnauthorized: false), insecure deserialization (eval, new Function, yaml.load unsafe, pickle), prototype pollution via deep merge of user JSON.
8. SECURITY MISCONFIGURATION (A05): verbose error responses with stack traces, debug mode flags on in production config, missing security headers set in code, permissive CSP.

Do not repeat hardcoded-secret or .gitignore issues (another agent covers them) or vulnerable package versions (another agent covers them).
Use Grep for sinks and sources, then Read the surrounding code to confirm the input really is attacker-controlled before reporting. Skip anything you cannot confirm; say "unconfirmed" in the description if you keep a likely-but-unproven one, and rate it no higher than MEDIUM.

Severity: HIGH = attacker-controlled input reaches the sink with no effective protection and impact is data theft, account takeover, money, or server compromise. MEDIUM = needs a precondition (logged-in user, specific config) or impact is limited. LOW = defense-in-depth gap.

Return findings as:
- [HIGH|MEDIUM|LOW] description — file:line | owasp: <A0x Name> | cwe: <CWE-nnn> | exploit: easy|moderate|hard | scenario: <one plain sentence: who could do what, through which entry point, and what they gain> | why: ... | fix: ...
Max 15 findings. No prose.
```

### Agent 8: Exploitable Loopholes (attacker's-eye review)

```
You are auditing a <context>.

You are a defensive reviewer thinking like an attacker, so the team can close loopholes before someone finds them. Read the source code only. Do NOT send requests to any running system, run exploits, or write working payloads, scripts or proof-of-concept code. Describe each loophole as a short plain-language scenario.

Step A — map the attack surface (keep this internal, do not output it): list the entry points an outsider can reach — public routes/pages, server/API endpoints and handlers, webhooks, file uploads, query/route parameters that change behaviour, forms (login, signup, password reset, checkout, coupons, gift cards, reviews, contact), third-party callbacks, and anything the client sends that the server trusts.

Step B — for each entry point, ask how it could be abused. Look for:

1. BUSINESS-LOGIC ABUSE: prices, totals, discounts, shipping costs, tax or quantities calculated or decided in the client and sent to the server; negative or zero quantities; coupon/gift-card/promo reuse or stacking; race conditions on balances (double spend); skipping a checkout step by calling a later endpoint directly; order status changed by the client.
2. ENUMERATION and GUESSABLE IDs: sequential or predictable order/user/invoice IDs in URLs or APIs that work without proof of ownership (guest order tracking by ID only, email-only lookups); login/reset/signup responses that reveal whether an account exists.
3. MISSING LIMITS: no rate limiting or CAPTCHA on login, OTP, password reset, gift-card balance check, coupon validation, contact/email-sending forms, search or expensive server-side rendering; no request size limits; unbounded pagination; no timeouts on outbound calls (resource exhaustion).
4. TRUST BOUNDARY MISTAKES: server trusting client-supplied role/customer_id/store_id/price/flags, hidden form fields or localStorage values used for authorization, webhooks accepted without signature verification, Host/X-Forwarded-* headers trusted for redirects, links or cache keys (cache poisoning).
5. CHAINS: two smaller weaknesses that combine into a serious one (e.g. an open redirect plus a token in the URL, or SSR shared state plus a user-specific value). Name each link of the chain with file:line.
6. EXPOSED INTERNALS: debug/test/admin pages or endpoints shipped to production, source maps published, internal API base URLs or environment switches controllable from the client, verbose errors revealing internal hosts.

Report only loopholes you can point to in code. If the protection might live in a backend you cannot see (e.g. the frontend sends a price but the backend may recalculate it), still report it as "depends on backend — verify" and rate it no higher than MEDIUM.

Severity: HIGH = an outsider or ordinary customer can gain money, data or another user's access with little effort. MEDIUM = needs an account, special timing, or backend behaviour to confirm. LOW = makes other attacks easier.

Return findings as:
- [HIGH|MEDIUM|LOW] description — file:line (and file:line for each link of a chain) | owasp: <A0x Name> | cwe: <CWE-nnn> | exploit: easy|moderate|hard | scenario: <one or two plain sentences: who, which entry point, what they do, what they gain> | why: ... | fix: ...
Max 15 findings. No prose.
```

### Agent 9: Security Controls Gap Analysis (OWASP ASVS Level 1)

```
You are auditing a <context>.

Read-only review. Compare the project against a standard baseline of security controls (OWASP ASVS 4.0 Level 1, plus basic DevSecOps practice) and report, for each control, whether it is in place, partial, missing, or not applicable to this project. Look at source code, server/framework config, CI files (Jenkinsfile, GitHub Actions, GitLab CI), Dockerfiles, Kubernetes/Helm, and package scripts.

Check these controls (add others only if clearly relevant to this stack):
- Authentication: password policy / delegated auth, brute-force protection (rate limit or lockout), secure password reset, MFA option for admins
- Session management: tokens in HttpOnly/Secure/SameSite cookies or equivalent, session expiry and logout invalidation, CSRF protection for cookie auth
- Access control: server-side authorization on every sensitive endpoint, ownership checks on object IDs, deny-by-default routing
- Input validation and output encoding: central validation of request data, framework auto-escaping not bypassed, safe file upload handling
- Security headers: Content-Security-Policy, HSTS, X-Frame-Options/frame-ancestors, X-Content-Type-Options, Referrer-Policy, CORS allow-list
- Transport: HTTPS enforced and HTTP redirected, TLS verification not disabled for outbound calls
- Secrets management: secrets from a secret store or CI credentials, none in git, separate keys per environment, rotation process
- Error handling and logging: generic error responses, central logger, security-event logging (logins, failures), no sensitive data in logs, alerting/monitoring hooked up
- Rate limiting / abuse protection: API and form rate limits, bot protection on public forms, request size limits
- Dependency and supply chain: lockfile committed, automated vulnerability scanning in CI (npm audit, Dependabot, Snyk, Sonar), pinned base images, supported runtime version
- Testing and CI gates: automated tests run in CI, security/static analysis (SAST) in CI, build fails on high-severity issues
- Data protection: personal data minimised in client storage and logs, payment data handled only by the payment provider (PCI scope reduced)
- Infrastructure: containers run as non-root, production debug features off, admin/test routes not exposed

For each control return exactly one line:
- <AREA> | <control> | <in place|partial|missing|not applicable> | <evidence: file:line or what you searched for and did not find, in one plain sentence> | <severity if missing/partial: HIGH|MEDIUM|LOW|-> | <fix: one sentence, or ->

Mark "missing" only after searching for it; say what you searched. Do not repeat individual vulnerabilities in detail (other agents cover them) — this is about whether the protection exists at all.
Max 35 lines. No prose.
```

## Step 3: Aggregate and rate

After all the selected agents return their findings:

1. Collect all findings into a single list.
2. Deduplicate: if two agents flagged the same file:line or essentially the same issue, merge them into one finding and record the other categories in `also_flagged_by`. Agent 7 findings use category `Vulnerabilities` and Agent 8 findings use category `Loopholes`; when they overlap with each other or with Agent 4 (`Security`), keep the one with the attack scenario and list the others in `also_flagged_by`.
   - **Gap analysis (Agent 9)**: keep its control table for the `gap_analysis` block (Step 4). Turn each `missing` or `partial` control rated HIGH or MEDIUM into a `Security` finding *unless* it is already covered by another finding — in that case put that finding's id in the control's `finding` field instead of duplicating it.
   - **Verify security findings before rating them HIGH.** Open the cited code for every HIGH from Agents 7 and 8 and confirm the input is really attacker-controlled and unprotected. Downgrade or drop anything that does not hold up; false alarms in a security report cost more trust than they are worth.
3. Sort by severity (high, medium, low), then by category in this order: Standards, Duplication, Logging, Security, Vulnerabilities, Loopholes, Testing, Dependencies. Number them `F1`, `F2`, ... in that order.
4. Give each finding an effort:
   - **quick** (< 30 min): renames, import reordering, missing .gitignore entries, removing debug leftovers, patch/minor dependency bumps
   - **medium** (30 min - 2 h): extracting shared helpers, deduplicating functions, standardizing a pattern, adding a missing test file, a major dependency upgrade, a missing lockfile
   - **complex** (> 2 h): architectural refactors, major security fixes, cross-cutting pattern changes, vulnerability chains that need coordinated upgrades
5. Decide a fix order (shared code and utilities first, then refactors, then tests, then cosmetic changes; move security ahead when there are HIGH security findings) and a verification checklist that uses this project's real build and test commands.

## Step 4: Write the report in plain language

The report is read by developers, leads and sometimes managers, so write every finding so someone outside the code can follow it. For each finding, fill in:

- **title**: a short headline (under ~12 words) that names the problem, e.g. "Error messages swallowed in brand dialog", not "Inconsistent error handling pattern".
- **what**: what is wrong, with the concrete detail (the function, the value, the package version).
- **why**: the consequence in everyday terms (a user sees a blank screen, a key can be copied from the built site, a fix has to be made in four places).
- **fix**: the specific change to make, not "consider refactoring".
- For `Vulnerabilities` and `Loopholes` findings, also fill in **attack_scenario** (one or two plain sentences: who could do what, through which entry point, and what they gain — no payloads or exploit code), **exploitability** (`easy`, `moderate` or `hard`), **owasp** (e.g. `A01 Broken Access Control`) and **cwe** (e.g. `CWE-639`). These are optional for other categories but useful for `Security` findings too.

Use the agents' `why` and `fix` notes as the starting point. Open the cited code when a note is too thin to explain clearly, because a vague finding is the main thing that makes an audit look unprofessional. Avoid jargon where an ordinary word works, and spell out acronyms the first time.

Also write a 2-4 sentence **summary**: the overall state of the code, the biggest risks, and what to tackle first.

Save everything as JSON in the format described in `references/report-data.md` (read it before writing the file). Set `root` to the project's absolute path, so every file in the report becomes a clickable link that opens in VS Code, and give every code finding its `locations` with paths relative to that root.

If the user asked for a live-site check, add a `live_site` block to the JSON so the report shows a plain-language "Live site check" section. Its shape: `{ "site": "<host>", "intro": "<one friendly sentence>", "targets": [{ "url", "status", "tls", "cert", "note" }], "good": ["plain sentences about what is configured correctly"], "issues": ["plain sentences about what is missing, each pointing to its finding id"] }`. Write `good`/`issues` in everyday words, not jargon.

If Agent 9 ran, add a `gap_analysis` block so the report shows a "Security gap analysis" table: `{ "baseline": "OWASP ASVS 4.0 Level 1", "intro": "<one plain sentence>", "controls": [{ "area", "control", "status": "missing|partial|in place|not applicable", "evidence", "finding": "<F-id if a finding covers it>" }] }`. Write `evidence` in plain words. Also set `"reviewers"` to the number of agents that ran.

Save the JSON as `<REPORT_DIR>/code-audit-<YYYY-MM-DD>.json` (REPORT_DIR defaults to `audit-reports/`). If a file with that name exists, add `-2`, `-3`, ... rather than overwriting an earlier audit.

## Step 5: Build the HTML report

Render the report with the bundled script, which produces one self-contained HTML file (no internet needed, prints cleanly to PDF):

```bash
python3 <this skill's directory>/scripts/render_report.py <REPORT_DIR>/code-audit-<date>.json <REPORT_DIR>/code-audit-<date>.html
```

The script checks the data and stops with a message if a field is wrong; fix the JSON and run it again. Using the script rather than writing HTML by hand keeps every report in the same layout: a cover with a health score, summary cards, a severity bar, "fix these first", a "Live site check" section (when a `live_site` block is present), results by area, finding cards colored by severity with clickable file paths, the implementation plan, and a short methodology note.

Then try to open it (`xdg-open` on Linux, `open` on macOS, `start` on Windows); if that fails, just give the path.

If `REPORT_DIR` is not in `.gitignore`, mention it in the reply so the user can decide whether audits should be committed. Don't edit `.gitignore` yourself.

## Step 6: Reply in the chat

Keep the chat reply short, because the detail is in the report:

```markdown
**Code audit: <project> (<scope>)** — health score <score>/100, grade <grade>
<H> high · <M> medium · <L> low
Security: <V> vulnerabilities · <X> exploitable loopholes · gap analysis <missing> missing / <partial> partial of <total> controls   (only the parts that ran)

Fix these first:
1. <title> — [file.ts:42](relative/path/file.ts#L42)
2. ...
(up to 5 high findings; if there are none, the top medium ones)

Full report: [code-audit-<date>.html](<REPORT_DIR>/code-audit-<date>.html)
```

Do not start fixing anything yet. If the user said No to fixes in Step 0, stop here. If they said Yes, continue to Step 7. Otherwise, offer it: "Want me to start fixing some of these?"

## Step 7: Fix issues with the user (optional, only when asked)

Act as a pair-programmer working through the report, not a batch script. Never auto-apply everything at once.

1. **Ask what to tackle.** With `AskUserQuestion`, offer sensible batches rather than 70 individual choices — e.g. "All quick wins", "The high-severity code issues", "A specific area (logging / duplication / tests / …)", or "Specific finding IDs". Let the user pick.
2. **Work in a safe place.** If the working tree is dirty or on the default branch, create a branch first (e.g. `fix/code-audit-<date>`). Make one focused commit per finding or per small group, with the finding id in the message. Only commit when the user has asked you to; otherwise leave the edits unstaged for them to review.
3. **Respect what should NOT be auto-edited:**
   - **Leaked secrets** (committed keys/tokens): do not just delete the line and move on. The real fix is to **rotate the credential** and remove it from history — that is the user's action on their provider. Make the code change (switch to env/secret manager, add to `.gitignore`), but tell the user plainly that the key must be rotated and that editing the file does not un-leak it.
   - **Dependency major upgrades / framework upgrades:** propose the command (`npm update`, `ng update`, etc.) and let the user run it; don't force-upgrade across majors unattended.
   - **Vulnerabilities and loopholes:** fix the root cause (server-side check, allow-list, encoding, rate limit), not a client-side patch that only hides it. If the real fix belongs in a backend or infrastructure you can't see (another repo, the ingress, a WAF), make the change you can and tell the user exactly what still needs doing elsewhere. Don't write exploit code to "prove" a fix; verify by reading the code path and with normal unit tests.
   - Anything the user didn't select.
4. **Verify after each batch.** Run the project's real build/test/lint commands (from Step 1) and report the result honestly. If a fix breaks the build or a test, say so and either fix forward or revert that change — don't leave the tree broken.
5. **Prefer the existing tools.** For pure cleanup (reuse, simplification, dead code) the `simplify` skill and for bug-hunting the `code-review` skill already exist — use them where they fit instead of re-deriving the work.
6. **Report back** which findings were fixed, which were skipped and why, and what still needs the user (rotations, upgrades, decisions). Do not mark a finding fixed unless the verification in step 4 passed.

Keep the user in control at each step: small batches, verify, confirm before moving on.
