# Report data format

`scripts/render_report.py` reads one JSON file and writes the HTML report. Write the file with these fields.

```json
{
  "project_name": "buchheit_pim_frontend",
  "project": "Angular 15 + TypeScript, Karma/Jasmine tests",
  "root": "/home/me/Projects/buchheit_pim_frontend",
  "scope": "frontend/src/app/pim/pages/brands",
  "date": "2026-10-28",
  "summary": "The brands module is in fair shape. The main risks are two error handlers that swallow failures and a copy-pasted error snackbar block in four files. Tests exist but only check that components are created.",
  "findings": [
    {
      "id": "F1",
      "severity": "high",
      "category": "Security",
      "title": "API key written directly in the environment file",
      "what": "The Google Maps key is a plain string in environment.prod.ts, which is committed to git.",
      "why": "Anyone with access to the repo or the built JavaScript can copy the key and use your quota.",
      "fix": "Move the key to the deploy pipeline's secrets and inject it at build time; rotate the current key.",
      "effort": "medium",
      "locations": [{ "path": "frontend/src/environments/environment.prod.ts", "line": 12 }],
      "also_flagged_by": ["Logging"]
    },
    {
      "id": "F2",
      "severity": "medium",
      "category": "Dependencies",
      "title": "Angular is two major versions behind",
      "what": "@angular/core is on 15.2.0; the latest is 17.3.0.",
      "why": "Older majors stop getting security fixes, and the gap gets harder to close the longer it waits.",
      "fix": "Upgrade one major at a time with `ng update`, running the tests after each step.",
      "effort": "complex",
      "package": "@angular/core@15.2.0 (15.2.0 -> 17.3.0)"
    }
  ],
  "fix_order": [
    { "step": "Security first", "why": "Leaked secrets cause damage until they are rotated." },
    { "step": "Shared helpers", "why": "Later refactors build on them." }
  ],
  "verification": [
    "TypeScript compiler reports 0 errors",
    "All tests pass",
    "New tests cover previously untested files"
  ],
  "tool_notes": ["npm audit ran on frontend/package-lock.json", "pip-audit not installed, Python checks skipped"]
}
```

## Fields

| Field | Required | Notes |
|---|---|---|
| `project_name` | yes | Short name shown as the report title, usually the repo folder name. |
| `project` | yes | The 1-line stack description from Step 1. |
| `root` | yes | Absolute path of the project root. Turns every location into a clickable VS Code link. |
| `scope` | yes | The scoped path, or `"Full project"`. |
| `date` | no | `YYYY-MM-DD`; defaults to today. |
| `summary` | yes | 2-4 plain sentences: overall state, the biggest risks, and what to do first. Write it for a manager as much as a developer. |
| `findings[].id` | no | `F1`, `F2`, ... in report order; generated if missing. |
| `findings[].severity` | yes | `high`, `medium` or `low`. |
| `findings[].category` | yes | Exactly one of `Standards`, `Duplication`, `Logging`, `Security`, `Testing`, `Dependencies`. |
| `findings[].title` | yes | Short headline, under ~12 words. |
| `findings[].what` | yes | What is wrong, in plain words, with the concrete detail. |
| `findings[].why` | yes | The consequence for the team or users, without jargon. |
| `findings[].fix` | yes | The concrete change to make. |
| `findings[].effort` | yes | `quick` (< 30 min), `medium` (30 min - 2 h) or `complex` (> 2 h). |
| `findings[].locations` | for code findings | List of `{ "path": <relative to root>, "line": <number> }`. Use every file:line the finding mentions. |
| `findings[].package` | for dependency findings | `name@version (current -> latest)`. |
| `findings[].also_flagged_by` | no | Other categories that reported the same issue (from deduplication). |
| `fix_order` | yes | Ordered steps, each `{ "step", "why" }`. |
| `verification` | yes | Checklist items adapted to the project's real commands. |
| `tool_notes` | no | Which audit tools ran or were missing. |
