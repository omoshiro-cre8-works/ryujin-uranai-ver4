# AGENTS.md

Last reviewed: 2026-09-22
Project: Webアプリ開発プロジェクト

## Purpose and responsibility

This repository is maintained as part of the Webアプリ開発プロジェクト.

Codex should focus on implementation work that has been explicitly requested, such as:

- reading and tracing existing code
- investigating impact across files
- making approved code changes
- running approved tests
- reviewing diffs
- reporting implementation results and unresolved risks

ChatGPT handles requirements, research, architecture, planning, implementation instructions, and review support.
The human owner approves requirements, acceptance criteria, Git write operations, releases, production changes, and other high-impact actions.

## Default operating mode

Start with read-only inspection unless the task explicitly authorizes changes.

Without explicit approval, do not:

- modify files
- commit
- push
- create or update a pull request
- merge
- rebase
- amend
- force push
- build or publish an image
- deploy to staging or production
- change external-service settings or data

Approval must be specific to the operation, target, branch, and environment. If the approved boundary is unclear, stop and ask.

## Source of truth and task grounding

Use the actual system state as the source of truth:

- GitHub for repository content, branches, commits, pull requests, and history
- Google Cloud for services, revisions, traffic, IAM, Secret references, and Firestore state
- Stripe for Products, Prices, Checkout, payments, and Webhooks
- Wix for published pages, CMS, Velo, settings, and purchase-path presentation
- GA4 and related analytics systems for received events and analysis readiness

Project documents are reference copies and operating records. Do not treat a document, chat history, or handoff note as proof of current system state when the live system can be read back.

If sources conflict, do not silently reconcile them. Report the mismatch, identify the authoritative source for each fact, and stop where a decision is required.

## Canonical repository, branch, and HEAD

- Use the repository and canonical branch explicitly identified for the task.
- Do not assume `main`, any default branch, or any historically used branch is canonical.
- Before editing, verify the repository, current branch, base branch, and HEAD when possible.
- If the task depends on a recorded HEAD, compare it with the current remote state before proceeding.
- Do not modify, push to, merge, or otherwise alter unrelated or historical pull-request branches unless explicitly authorized.
- Do not switch the canonical branch or reinterpret branch history without approval.
- Avoid force push, rebase, amend, history rewriting, and destructive branch operations unless explicitly approved.

## Git write-operation approval

Git operations are separate approval stages. Approval for one stage does not authorize the next.

- code-change approval does not imply commit approval
- commit approval does not imply push approval
- push approval does not imply pull-request creation or update approval
- pull-request creation does not imply merge approval
- merge approval does not imply build or deploy approval

Before any approved commit:

- confirm the intended branch and HEAD
- confirm only expected files changed
- inspect the final diff
- confirm there is no line-ending or encoding explosion
- run the required tests and `git diff --check` or an equivalent check
- report any unrelated working-tree changes without overwriting them

Before any approved pull request:

- confirm the correct base and head branches
- confirm the scope and acceptance criteria
- summarize tests, risks, and unresolved items

Never merge unless merge has been separately and explicitly authorized.

## Scope discipline

Only change files required for the approved task.

Do not perform unrelated:

- refactoring
- formatting
- import reordering
- dependency upgrades
- repository-wide cleanup
- generated-file replacement
- line-ending normalization
- `.gitattributes` changes

If an unrelated issue is found, report it. Fix it only when it blocks the approved task and the additional change is explicitly approved.

Preserve existing user changes and unrelated working-tree changes. Do not discard, reset, overwrite, or revert them.

## Line endings and encoding

Preserve the repository's existing line endings and encoding.
Do not convert LF/CRLF across entire files as a side effect of an edit.
Before commit, verify that the diff does not show whole-file changes caused by line endings, encoding, or formatting tools.

## Environment separation

Keep local, test, staging, and production environments distinct.

When working on staging:

- use staging Cloud Run services only
- use the intended named staging Firestore database and collection
- use Stripe test mode only
- use staging Secrets and service accounts only
- use staging URLs and callbacks only
- do not fall back to production resources
- do not copy production settings unless their necessity and safety have been verified

If a production URL, live Stripe credential, production Firestore reference, or production Secret appears unexpectedly in a staging path, stop and report it.

## Production safety

Production actions require explicit human approval for the exact target and operation.

Without that approval, do not:

- deploy production Cloud Run services
- create or shift production traffic
- change production environment variables
- change production IAM
- change production Secrets or Secret IAM
- create, update, or delete production Firestore data
- change Stripe live-mode resources
- change production Wix pages, CMS, Velo, or settings
- change production analytics configuration
- merge production-sensitive pull requests
- perform destructive cleanup

Do not treat approval for local work, staging, review, merge, or build as production authorization.

## Secrets and sensitive data

Never print, copy, summarize, commit, upload, or expose:

- Secret payloads
- API keys
- Stripe secret keys
- webhook signing secrets
- passwords or passphrases
- access, recovery, or purchase tokens
- credentials or private customer data

Do not read Secret payloads unless the task explicitly requires it and human approval is clear. Prefer confirming Secret names, versions, references, or bindings without revealing values.

Do not place secret values in source code, Git history, chat reports, screenshots, ordinary documents, or command output.

## Personal data, images, and generated content

For personal information, uploaded images, consultation content, payment-related records, or generated files, identify:

- whether the data is stored
- the storage location
- the minimum fields required
- retention and deletion rules
- external transmission
- access controls
- privacy-policy or terms implications

Minimize collection and retention. Do not broaden logging or storage without explicit approval.

## Purchase and rescue boundaries

Do not modify purchase, generation, PDF, reload, or rescue behavior unless explicitly included in the task.

Separate approval is required for changes involving:

- `used_flag` semantics
- `processing`
- `pdf_generated`
- self-resume or recovery tokens
- admin rescue tokens
- `rescue_status`
- reload recovery
- double-generation prevention
- purchase recovery models
- Stripe idempotency or replay behavior

Treat these as payment and customer-protection logic, not incidental refactoring.

## Firestore safety

- Do not create, update, or delete Firestore documents unless explicitly authorized.
- Treat test-data cleanup as a separate operation from code changes.
- Verify the intended project, database, collection, and document path before any approved write.
- Use the intended named staging database when staging is specified.
- Do not run broad queries, migrations, or bulk deletion unless specifically approved and recoverability has been considered.
- Preserve delete protection and other safety controls unless their change is explicitly authorized.

## Stripe safety

- Use Stripe test mode for staging work.
- Do not create, activate, archive, or modify live-mode Products, Prices, Webhooks, or other resources without explicit human approval.
- Do not assume a Product or Price should be created when an existing asset may be reusable.
- Verify test/live mode, amount, currency, Price ID, Product, metadata, success/cancel URLs, and Webhook behavior before release.
- Never expose secret keys or signing secrets in reports.

Price changes are coordinated releases. A code change alone does not complete a price change. Confirm the required alignment among Stripe, Cloud Run, Wix, Firestore records, analytics values, documentation, testing, and rollback.

## Cloud Run, Secret Manager, and IAM safety

Use least privilege.

Do not add broad roles proactively because a permission error might occur. If a permission is missing:

1. capture the exact non-secret error
2. identify the minimum required permission or role
3. identify the exact principal and resource scope
4. stop
5. request approval before changing IAM

Do not add Owner, Editor, broad Cloud Run administration, broad Secret Manager access, or project-wide Storage access unless explicitly authorized and justified.

For Cloud Run work, verify the service, region, revision, image digest, traffic, runtime service account, environment variables, Secret references, URLs, and downstream resources appropriate to the approved environment.

## Wix and analytics safety

- Treat Wix draft/editor state and the published site as different states.
- Do not change production Wix pages, CMS, Velo, SEO, pricing text, or purchase paths without explicit approval.
- Verify published behavior after an approved Wix release.
- Do not treat event implementation as analytics readiness.
- For analytics, distinguish code implementation, event transmission, event reception, stored values, and report usability.
- Keep UTM and purchase-attribution behavior consistent across Wix and external applications.

## Build and deploy separation

Build and deployment are separate approval stages.

- approval to merge does not authorize build
- approval to build does not authorize deploy
- approval to deploy to staging does not authorize production deploy
- production deploy always requires explicit human approval

For an approved build-only task:

- build from the approved commit
- push only to the approved registry and environment
- record the immutable image digest
- stop before deploy

For an approved deploy task:

- deploy the approved commit or immutable digest
- verify the resulting revision and configuration
- verify traffic only within the approved scope
- stop before E2E unless E2E is included or separately approved

Do not use mutable tags such as `latest` when a full Git SHA or immutable digest is required.

## Testing standard

For an approved code change:

1. run focused tests for the changed behavior
2. run relevant regression tests
3. run the full test suite when practical
4. run `git diff --check` or an equivalent check
5. review the final diff for unrelated changes
6. distinguish failures caused by the current change from pre-existing failures

Do not fix unrelated failing tests without approval.
Do not claim success when a required test, integration, environment, or external-service check remains unverified.

## E2E and completion states

Keep the following states distinct when reporting:

- investigated
- implementation completed
- local tests passed
- commit created
- pushed
- pull request created or reviewed
- merged
- build completed
- staging deployed
- staging E2E passed
- production preflight completed
- production deployed
- production E2E passed
- external-service receipt verified
- persistence verified
- analytics receipt and usability verified
- documentation and source-of-truth records updated

Do not describe code completion as deployment, deployment as successful operation, or event transmission as analysis readiness.

## Risk-based verification

### Level A — local-only work

Examples: read-only investigation, code edits, tests, approved commits, and pull-request diffs.

Focus verification on code, tests, the working tree, branch/HEAD, and diff. Rechecking unchanged production infrastructure is normally unnecessary.

### Level B — staging changes

Examples: staging build, Cloud Run, IAM, Secret mapping, Firestore, Stripe test, or E2E.

Focus on changed staging resources and only the production baselines necessary to prove non-impact.

### Level C — production changes

Use strict preflight, explicit human approval, exact-target confirmation, postflight verification, rollback readiness, and a completion record.

## Efficient Codex usage

Prefer completing one approved, safe implementation unit in one turn:

1. inspect relevant code and instructions
2. confirm impact paths and approved scope
3. implement the minimal approved change
4. run focused and relevant regression tests
5. run the full test suite when practical
6. review the diff
7. commit only if explicitly authorized
8. stop at the approved boundary and report

Avoid repeated re-reading of unchanged infrastructure state unless the task genuinely depends on it. Do not repeatedly verify production Cloud Run, IAM, Secrets, Firestore, or Stripe for local-only changes.

## Reporting standard

Report concisely:

- repository, branch, and HEAD used
- what changed
- files changed
- why the change was made
- tests and checks run, with results
- impact and risk
- what was not changed
- external systems not verified
- unresolved items
- rollback considerations
- the exact approved boundary where work stopped

Never report an unverified state as confirmed.

## Stop conditions

Stop and report instead of improvising when:

- the repository, canonical branch, base branch, HEAD, target environment, or resource is ambiguous
- the requested operation exceeds the approved scope
- unrelated user changes overlap the task
- production resources appear in a staging path
- live Stripe mode appears unexpectedly
- a Secret value would need to be exposed
- IAM permissions are missing or broader access appears necessary
- a destructive data operation would be required
- the diff is unexpectedly large
- line-ending, encoding, generated-file, or formatting changes appear unexpectedly
- tests fail for unclear reasons
- build or deploy requires broader permissions or a different target than approved
- rollback is unavailable for a high-impact change
- system state conflicts with the recorded project documentation

## Explicit human confirmation required

Always require explicit human confirmation before:

- modifying code when the task began as read-only investigation
- commit
- push
- pull-request creation or update
- merge
- build or image publication
- staging deploy
- production deploy or traffic change
- Stripe live-mode changes
- production Secret changes or Secret-value entry
- production Firestore writes, migrations, or destructive changes
- broad or production IAM changes
- production Wix publication or configuration changes
- destructive cleanup
- rollback that changes a shared or production environment

When confirmation is given, apply it only to the exact operation and target described. Do not infer approval for subsequent stages.
