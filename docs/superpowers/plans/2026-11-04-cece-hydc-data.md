# CECE HYDC Data Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make HYDC the dev172 CECE business-data skill with fixed transport settings and environment-only credentials.

**Architecture:** Rename the public skill to `cece-hydc-data`. Its Node wrapper accepts only an action and business command, reads `HYDC_API_KEY` from the sandbox environment, and uses a fixed HTTPS endpoint and timeout. Dev172 configuration points only to the renamed package.

**Tech Stack:** Node.js built-in `fetch` and `node:test`; YAML and JSON deployment templates.

**Spec:** Conversation-approved HYDC integration plan (2026-11-04).

## Global Constraints

- Do not make a live HYDC request in tests.
- Never accept API keys, endpoint URLs, or timeout values from command-line arguments.
- Do not add secrets to tracked files.
- Keep test224 untouched; this applies to dev172 only.

## Review Focus

- Importing the Node module must not issue a request or terminate the process.
- Business-command flags such as `--keyword` must remain part of the transmitted command.
- Missing `HYDC_API_KEY` must fail without echoing a secret.
- Fixed endpoint and timeout must not be user-overridable.
- All dev172 prompt paths must match the renamed skill directory.

### Task 1: Constrain and test the HYDC transport wrapper

**Files:**
- Create: `tests/skills/test_cece_hydc_data.mjs`
- Rename: `skills/public/hydc-industry-insight/` to `skills/public/cece-hydc-data/`
- Modify: `skills/public/cece-hydc-data/scripts/hydc.mjs`

- [ ] Write offline tests that assert CLI parsing retains business flags, rejects wrapper override flags, uses `HYDC_API_KEY` only, and posts to the fixed endpoint with the fixed timeout.
- [ ] Run the test and verify it fails against the current wrapper interface.
- [ ] Implement the minimum import-safe wrapper changes and run the test green.

### Task 2: Rewrite the operator-facing Skill and deployment references

**Files:**
- Modify: `skills/public/cece-hydc-data/SKILL.md`
- Modify: `deploy/cece-harness-dev172/config.example.yaml`
- Modify: `deploy/cece-harness-dev172/README.md`

- [ ] Add structural tests for the renamed skill name, env-only credential guidance, fixed invocation, and dev172 path.
- [ ] Run tests and verify they fail before the documentation/configuration changes.
- [ ] Update the public skill and deployment templates, then run all focused tests and configuration parsing.

### Task 3: Review the resulting change

- [ ] Scan the diff for old paths, forbidden CLI switches, and secret-looking literals.
- [ ] Run the full focused suite and report the exact deployment values still required from the operator.
