#!/usr/bin/env python3
"""CDK app entry point.

Required environment variables:
  AWS_ACCOUNT_ID   — 12-digit AWS account number
  SITE_HOSTNAME    — public hostname, e.g. traffic.example.com
  GITHUB_REPO      — owner/repo, e.g. myorg/liikennevirta

The infrastructure is split across two stacks because ACM certificates used
by CloudFront must exist in us-east-1, while all other resources live in
eu-north-1. CDK cross-region references (backed by SSM) wire them together.

First-time setup:
  cd infra
  uv sync && npm install
  npx aws-cdk bootstrap aws://$AWS_ACCOUNT_ID/us-east-1
  npx aws-cdk bootstrap aws://$AWS_ACCOUNT_ID/eu-north-1
  npx aws-cdk deploy --all
"""
import os
import sys

import aws_cdk as cdk
from liikennevirta_stack import CertificateStack, LiikennevirstaStack

for var in ("AWS_ACCOUNT_ID", "SITE_HOSTNAME", "GITHUB_REPO"):
    if not os.environ.get(var):
        sys.exit(f"Missing required environment variable: {var}")

account = os.environ["AWS_ACCOUNT_ID"]
hostname = os.environ["SITE_HOSTNAME"]
github_repo = os.environ["GITHUB_REPO"]

app = cdk.App()

cert_stack = CertificateStack(
    app,
    "LiikennevirrtaCert",
    hostname=hostname,
    env=cdk.Environment(account=account, region="us-east-1"),
    cross_region_references=True,
)

LiikennevirstaStack(
    app,
    "Liikennevirta",
    hostname=hostname,
    github_repo=github_repo,
    certificate=cert_stack.certificate,
    env=cdk.Environment(account=account, region="eu-north-1"),
    cross_region_references=True,
)

app.synth()
