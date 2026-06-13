# Bootstrapping — deploying to AWS

This guide walks through every step needed to provision the AWS infrastructure and get the site live for the first time. Subsequent deployments are handled automatically by GitHub Actions.

---

## What you will need

Gather these before you start:

| Item | Description | Example |
| --- | --- | --- |
| AWS account number | 12-digit identifier shown in the AWS console top-right corner | `123456789012` |
| Public hostname | The domain name visitors will use; you must control its DNS | `traffic.example.com` |
| GitHub repository slug | `owner/repo` as it appears in the repository URL | `myorg/liikennevirta` |

### Local tools

| Tool | Install |
| --- | --- |
| [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) | `brew install awscli` or the official installer |
| [Node.js](https://nodejs.org/) ≥ 18 | Required by the CDK CLI |
| [Python](https://www.python.org/) ≥ 3.14 | Already required for the project |
| [uv](https://docs.astral.sh/uv/) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |

Configure the AWS CLI with credentials that have administrator access — these are only used locally for the one-time bootstrap:

```bash
aws configure
```

---

## Step 1 — Install CDK dependencies

```bash
cd infra
uv sync        # CDK Python library into infra/.venv
npm install    # CDK CLI into infra/node_modules (no global install)
cd ..
```

---

## Step 2 — Bootstrap the CDK toolkit

CDK needs a small set of AWS resources in the account before it can deploy stacks (an S3 bucket for assets and IAM roles for CloudFormation). The infrastructure spans two regions — the main stack runs in `eu-north-1`, but CloudFront requires ACM certificates to exist in `us-east-1`, so both regions must be bootstrapped:

```bash
export AWS_ACCOUNT_ID=123456789012
npx aws-cdk bootstrap aws://$AWS_ACCOUNT_ID/eu-north-1
npx aws-cdk bootstrap aws://$AWS_ACCOUNT_ID/us-east-1
```

---

## Step 3 — Deploy the infrastructure stacks

The CDK app contains two stacks that must be deployed together:

| Stack | Region | Purpose |
| --- | --- | --- |
| `LiikennevirrtaCert` | `us-east-1` | ACM certificate (CloudFront requirement) |
| `Liikennevirta` | `eu-north-1` | S3, CloudFront, OIDC role |

```bash
export AWS_ACCOUNT_ID=123456789012
export SITE_HOSTNAME=traffic.example.com
export GITHUB_REPO=myorg/liikennevirta

cd infra
npx aws-cdk deploy --all
```

CDK will print a summary of what it will create and ask for confirmation. The resources provisioned are:

- **ACM certificate** (`us-east-1`) — for `traffic.example.com`, validated via DNS
- **S3 bucket** `traffic.example.com` (`eu-north-1`) — private, serves the static site via CloudFront
- **S3 bucket** `traffic.example.com-data` (`eu-north-1`) — private, stores raw Digitraffic CSV files
- **S3 bucket** `traffic.example.com-cf-logs` (`eu-north-1`) — private, stores CloudFront access logs
- **CloudFront distribution** — HTTPS only, OAC origin, access logging enabled
- **IAM OIDC provider** — trusts `token.actions.githubusercontent.com`
- **IAM role** (`liikennevirta-deploy`) — assumed by GitHub Actions to deploy

When the deploy finishes, the outputs are printed to the terminal. Note down the `CnameTarget` and `DistributionId` values — you will need them in the next steps.

---

## Step 4 — Validate the TLS certificate

During the deploy CDK creates an ACM certificate and waits for DNS validation. The terminal will show a CNAME record that you must add to your DNS:

```text
Name:   _abc123def456.traffic.example.com
Value:  _xyz789.acm-validations.aws.
```

Add this CNAME record at your DNS provider. Once AWS detects it (typically within a few minutes, but up to 30 minutes depending on the provider) the certificate becomes valid and the deploy completes.

> The deploy command will remain running until validation succeeds. Leave it open or re-run `npx aws-cdk deploy --all` if it times out — it will resume from where it left off.

---

## Step 5 — Add the public CNAME

After the deploy completes, the `CnameTarget` output shows the CloudFront domain:

```text
CnameTarget = d1abc2def3ghi4.cloudfront.net
```

At your DNS provider, add:

```text
traffic.example.com  CNAME  d1abc2def3ghi4.cloudfront.net
```

Propagation typically takes a few minutes. Once live, `https://traffic.example.com` will be served from CloudFront.

---

## Step 6 — Populate the data bucket

The CDK stack provisions a private S3 bucket named `traffic.example.com-data` to hold the raw Digitraffic CSV files. The CI workflow syncs from this bucket before running `build_data.py`. You populate it manually from your local machine.

Download the CSV files locally first by running the dev server and browsing to a date, or programmatically:

```python
from main import get_tms_data, TRIP_ORDER
for tms_id in TRIP_ORDER:
    get_tms_data(tms_id, "2025-06-13")
```

Then upload `tms_cache/` to the data bucket:

```bash
aws s3 sync tms_cache/ s3://traffic.example.com-data/tms_cache/
```

Repeat this sync whenever new dates are downloaded locally. The CI workflow will pick them up on the next push to `main`.

---

## Step 7 — Build and upload the first deployment

With `tms_cache/` populated, build the static files and push them to S3:

```bash
uv run python build_data.py

# Long cache for data files (content-addressed by date)
aws s3 sync dist/data/ s3://traffic.example.com/data/ \
  --cache-control "public, max-age=86400, immutable"

# Short cache for the index and date manifest
aws s3 sync dist/ s3://traffic.example.com/ \
  --exclude "data/*" \
  --cache-control "public, max-age=60"
```

Open `https://traffic.example.com` to verify the site is live.

---

## Step 8 — Configure GitHub Actions

All subsequent deployments run automatically when you push to `main`. Two repository variables need to be set before the workflow can run.

In the GitHub repository: **Settings → Secrets and variables → Variables → New repository variable**

| Variable | Value |
| --- | --- |
| `AWS_ACCOUNT_ID` | Your 12-digit AWS account number |
| `SITE_HOSTNAME` | `traffic.example.com` |

The data bucket name is derived from `SITE_HOSTNAME` (`traffic.example.com-data`) so no additional variable is needed.

No secrets are needed — authentication uses OIDC, so no long-lived AWS credentials are stored in GitHub.

Push any change to `main` to trigger the first automated deployment and confirm the workflow completes successfully.

---

## IAM deploy role

The `liikennevirta-deploy` role is created by the CDK stack and assumed by GitHub Actions via OIDC. It is intentionally minimal — it delegates all CloudFormation resource management to the CDK bootstrap roles and only holds direct permissions for the two workflow steps that run outside of CDK: the S3 sync and the CloudFront cache invalidation.

### What the role can do

| Permission | Resource | Why |
| --- | --- | --- |
| `ssm:GetParameter` | `/cdk-bootstrap/hnb659fds/version` (both regions) | CDK CLI reads the bootstrap version before deploying |
| `sts:AssumeRole` | `cdk-hnb659fds-deploy-role-*` (both regions) | CDK CLI assumes this role to trigger CloudFormation |
| `sts:AssumeRole` | `cdk-hnb659fds-file-publishing-role-*` (both regions) | CDK CLI assumes this role to upload stack assets to S3 |
| `sts:AssumeRole` | `cdk-hnb659fds-lookup-role-*` (both regions) | CDK CLI assumes this role for environment context lookups |
| `s3:ListBucket`, `s3:GetBucketLocation` | Data bucket | `aws s3 sync` lists CSV files before the build step |
| `s3:GetObject` | Data bucket objects | Downloads CSV files to the runner for `build_data.py` |
| `s3:ListBucket`, `s3:GetBucketLocation` | Site bucket | `aws s3 sync` needs to list existing objects |
| `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` | Site bucket objects | `aws s3 sync --delete` reads, writes, and removes objects |
| `cloudfront:CreateInvalidation` | All distributions in the account | Clears the CDN cache after each deploy |

### What creates the AWS resources

The role does **not** create or modify AWS resources directly. That work is done by `cdk-hnb659fds-cfn-exec-role`, which CloudFormation assumes and which is provisioned during `cdk bootstrap`. By default, the cfn-exec-role has `AdministratorAccess` — this is an AWS CDK default that can be tightened with a custom `--cloudformation-execution-policies` flag at bootstrap time.

### Trust policy

The role is only assumable by GitHub Actions OIDC tokens issued for pushes to the `main` branch of the configured repository:

```json
{
  "StringLike": {
    "token.actions.githubusercontent.com:sub": "repo:OWNER/REPO:ref:refs/heads/main"
  },
  "StringEquals": {
    "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
  }
}
```

---

## Ongoing operation

| Task | Command |
| --- | --- |
| Deploy infrastructure changes | `cd infra && npx aws-cdk deploy --all` (or push to `main`) |
| Add new traffic data locally | Run `app.py` or the programmatic fetch, then `build_data.py` |
| Update the CDK role if GitHub repo is renamed | Re-deploy with the new `GITHUB_REPO` value |
