# Webhook Docker Image Build and Digest Deployment Runbook

This runbook defines the repository-side workflow for the Stripe webhook Cloud Run service. It intentionally standardizes on Dockerfile builds and digest-pinned deploys. Do not add Buildpacks-only runtime files such as `.python-version` for this workflow.

## 1. Scope and Fixed Names

- Google Cloud project: `gen-lang-client-0636169164`
- Region: `asia-northeast2`
- Artifact Registry repository: `cloud-run-source-deploy`
- Webhook image: `ai-uranai-webhook`
- Canonical image path: `asia-northeast2-docker.pkg.dev/gen-lang-client-0636169164/cloud-run-source-deploy/ai-uranai-webhook`
- Webhook build context: `stripe_webhook`
- Webhook Dockerfile: `stripe_webhook/Dockerfile`
- Staging Cloud Run service: `ai-uranai-webhook-staging`
- Production Cloud Run service: `ai-uranai-webhook`

Builds and deploys are separate operations. A build may push a commit-tagged image, but it must not deploy to Cloud Run. Deploys must use an immutable image digest:

```text
<image-path>@sha256:<digest>
```

Do not deploy using `latest`, date-only tags, staging tags, or production tags.

## 2. Preflight: Fix the Target

Run these checks before requesting build approval:

```powershell
git fetch --all --prune
git status --short --branch
git rev-parse origin/ver5-direct-checkout
git rev-parse <target-commit>
git merge-base --is-ancestor 365268e <target-commit>; if ($LASTEXITCODE -eq 0) { "PR5 commit is included: STOP" } else { "PR5 commit is not included" }
git ls-tree <target-commit> stripe_webhook
git rev-parse <target-commit>:stripe_webhook
git rev-parse <target-commit>:stripe_webhook/Dockerfile
```

Confirm:

- The target commit is a full 40-character Git SHA.
- The working tree is clean.
- Local and remote branch heads match the intended target.
- PR #5 or other unapproved commits are not included.
- The source tree and Dockerfile hashes are recorded.
- No Secret values, credentials, or local `.env` files are part of the source.

## 3. Build Approval

Before building, a human reviewer must explicitly approve:

- The project, region, repository, image name, and target commit SHA.
- That `cloudbuild-webhook.yaml` contains only Dockerfile build steps.
- That the build context is `stripe_webhook`.
- That no Cloud Run deploy step is present.
- That no Secret Manager references, production environment variables, Stripe calls, Firestore calls, GA4 calls, or webhook sends are present.
- That the image tag is the full commit SHA only.

## 4. Build and Push the Image

Use `cloudbuild-webhook.yaml`. This config builds the image from `stripe_webhook/Dockerfile`, pushes it to Artifact Registry through the `images:` field, and stops. It does not deploy.
The config also verifies that `PROJECT_ID` matches the approved Artifact Registry project before building.

PowerShell example:

```powershell
$PROJECT = "gen-lang-client-0636169164"
$COMMIT = "<full-40-character-commit-sha>"

gcloud builds submit . `
  --project $PROJECT `
  --config cloudbuild-webhook.yaml `
  --substitutions "COMMIT_SHA=$COMMIT"
```

Bash example:

```bash
PROJECT="gen-lang-client-0636169164"
COMMIT="<full-40-character-commit-sha>"

gcloud builds submit . \
  --project "$PROJECT" \
  --config cloudbuild-webhook.yaml \
  --substitutions "COMMIT_SHA=$COMMIT"
```

The Cloud Build config validates that `COMMIT_SHA` is a 40-character lowercase hexadecimal SHA. If this check fails, stop and do not retry with a guessed commit.

## 5. Record Build Results

After the build finishes, record the build in `docs/templates/webhook-deployment-record.md`.

Digest lookup:

```powershell
$PROJECT = "gen-lang-client-0636169164"
$IMAGE = "asia-northeast2-docker.pkg.dev/$PROJECT/cloud-run-source-deploy/ai-uranai-webhook"
$COMMIT = "<full-40-character-commit-sha>"

gcloud artifacts docker images list $IMAGE `
  --project $PROJECT `
  --include-tags `
  --filter "tags:$COMMIT"
```

Also record:

- Cloud Build ID and status.
- Commit SHA and source tree hash.
- Dockerfile hash.
- Base image tag from the Dockerfile.
- Base image digest resolved during the build, when available from build logs or provenance.
- Output image path and digest.
- Build time.
- Test results.
- Build approver and executor.

Do not record Secret values, tokens, purchase IDs, full customer information, or private credentials.

## 6. Staging Deploy Preflight

Before deploying to staging, confirm:

- The target service is `ai-uranai-webhook-staging`.
- The project is `gen-lang-client-0636169164`.
- The region is `asia-northeast2`.
- The image is specified with `@sha256:<digest>`, not a tag.
- The digest is the same digest recorded from the approved build.
- The staging runtime service account is used.
- `APP_ENV=staging`.
- `STRIPE_MODE=test`.
- A staging Firestore project/database/collection is specified.
- Staging-only Secret references are used.
- No production Secret reference is used.
- The production service name is not present in the staging command.
- The current staging Revision, digest, traffic, environment variable names, Secret references, service account, CPU, memory, concurrency, timeout, ingress, and authentication settings are recorded.
- Deployment approval is explicit.

Example for a new staging service, not to be run without approval:

```powershell
gcloud run deploy ai-uranai-webhook-staging `
  --project gen-lang-client-0636169164 `
  --region asia-northeast2 `
  --image "asia-northeast2-docker.pkg.dev/gen-lang-client-0636169164/cloud-run-source-deploy/ai-uranai-webhook@sha256:<digest>" `
  --service-account "<staging-runtime-service-account>" `
  --port 8080 `
  --memory 512Mi `
  --cpu 1 `
  --concurrency 80 `
  --timeout 300 `
  --min-instances 0 `
  --max-instances 2 `
  --set-env-vars "APP_ENV=staging,STRIPE_MODE=test,FIRESTORE_PROJECT_ID=<staging-project>,FIRESTORE_DATABASE_ID=<staging-database>,FIRESTORE_COLLECTION_NAME=<staging-collection>" `
  --set-secrets "STRIPE_SECRET_KEY=<staging-stripe-test-secret>:<version>,STRIPE_WEBHOOK_SECRET=<staging-stripe-webhook-secret>:<version>" `
  --allow-unauthenticated
```

The webhook must be reachable by Stripe for webhook delivery tests. Use Stripe signature verification, test mode, staging-only signing secrets, and staging-only Firestore settings as the primary controls. Do not rely on an undisclosed URL as the security boundary.

## 7. Staging Acceptance Tests

Staging is accepted only when all of the following are true:

- Health check returns 200 for valid staging configuration.
- Invalid staging configuration returns a failure status.
- Unsigned and invalid-signature webhook POST requests return 4xx.
- Stripe test mode is used.
- Test webhook delivery reaches only the staging webhook service.
- Webhook processing writes only to the staging Firestore database/collection.
- Production Firestore is not touched.
- Production Secret references are not used.
- Responses and logs do not expose Secret values.
- The runtime is Python 3.11.x.
- The Revision, digest, commit, and build ID are recorded.
- Rollback is possible and the rollback target is recorded.

## 8. Production Promotion

Production promotion must use the same digest that passed staging. Do not rebuild for production.

Before production deploy, record:

- Current production Revision.
- Current production image digest.
- Current traffic split.
- Environment variable names.
- Secret reference names and versions.
- Runtime service account.
- CPU, memory, concurrency, timeout, ingress, and authentication settings.
- Rollback Revision and rollback digest.

Production deploy example, execution prohibited without separate approval:

```powershell
gcloud run deploy ai-uranai-webhook `
  --project gen-lang-client-0636169164 `
  --region asia-northeast2 `
  --image "asia-northeast2-docker.pkg.dev/gen-lang-client-0636169164/cloud-run-source-deploy/ai-uranai-webhook@sha256:<staging-validated-digest>" `
  --no-traffic
```

After a no-traffic candidate Revision is created, perform health checks and log checks. Any traffic change requires a separate explicit approval. Stripe live webhook delivery tests also require separate approval.

## 9. Rollback

First choice: move traffic back to the previous Ready Revision.

```powershell
gcloud run services update-traffic <service-name> `
  --project gen-lang-client-0636169164 `
  --region asia-northeast2 `
  --to-revisions "<previous-ready-revision>=100"
```

Second choice: create a new Revision from the previous digest.

```powershell
gcloud run deploy <service-name> `
  --project gen-lang-client-0636169164 `
  --region asia-northeast2 `
  --image "<previous-image-path>@sha256:<previous-digest>"
```

Rollback verification:

- Traffic is back on the intended Revision.
- Health check is healthy.
- Logs show no repeated configuration failures.
- Stripe retries are understood and monitored.
- Firestore updates remain idempotent.
- Duplicate webhook processing is not introduced.

Do not use deletion or configuration reset as a rollback method.

## 10. Stage 2 Prerequisites and Risks

These are intentionally not changed by this repository PR and must be resolved before staging construction:

- The Compute Engine default service account currently concentrates broad permissions.
- Build, deploy, and runtime service accounts are not yet separated.
- The staging runtime service account does not exist yet.
- The staging named Firestore database does not exist yet.
- Staging-only Secrets do not exist yet.
- Stripe test webhook endpoint does not exist yet.
- Artifact Registry vulnerability scanning is disabled.
- The current production Revision uses a different image path from the canonical Dockerfile build path.
- The staging Cloud Run service does not exist yet.
- The Cloud Build trigger has not been changed.

## 11. Non-Goals

This runbook does not change Cloud Run, Cloud Build triggers, Artifact Registry, IAM, Firestore, Secret Manager, Stripe, GA4, or production/staging data. It documents the intended workflow only.
