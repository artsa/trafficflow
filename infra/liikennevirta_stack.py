from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    CfnOutput,
    aws_certificatemanager as acm,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_iam as iam,
    aws_s3 as s3,
)
from constructs import Construct


class CertificateStack(Stack):
    """ACM certificate in us-east-1 — required by CloudFront."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        hostname: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.certificate = acm.Certificate(
            self,
            "Certificate",
            domain_name=hostname,
            validation=acm.CertificateValidation.from_dns(),
        )

        CfnOutput(self, "CertificateArn", value=self.certificate.certificate_arn)


class LiikennevirstaStack(Stack):
    """Main stack in eu-north-1 — S3, CloudFront, OIDC role."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        hostname: str,
        github_repo: str,
        certificate: acm.ICertificate,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── S3 bucket: site content ───────────────────────────────────────────
        site_bucket = s3.Bucket(
            self,
            "SiteBucket",
            bucket_name=hostname,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ── S3 bucket: raw traffic data (tms_cache) ──────────────────────────
        # Populated manually with CSV files from Digitraffic. CI reads from here
        # during the build step; it never writes back.
        data_bucket = s3.Bucket(
            self,
            "DataBucket",
            bucket_name=f"{hostname}-data",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ── S3 bucket: CloudFront access logs ─────────────────────────────────
        # BUCKET_OWNER_PREFERRED is required for CloudFront to write log objects.
        logs_bucket = s3.Bucket(
            self,
            "LogsBucket",
            bucket_name=f"{hostname}-cf-logs",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_PREFERRED,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ── CloudFront distribution ───────────────────────────────────────────
        distribution = cloudfront.Distribution(
            self,
            "Distribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(site_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                compress=True,
            ),
            additional_behaviors={
                # Data files are content-addressed by date; cache them longer.
                "/data/*": cloudfront.BehaviorOptions(
                    origin=origins.S3BucketOrigin.with_origin_access_control(site_bucket),
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=cloudfront.CachePolicy(
                        self,
                        "DataCachePolicy",
                        default_ttl=Duration.days(1),
                        max_ttl=Duration.days(365),
                        min_ttl=Duration.seconds(0),
                    ),
                    compress=True,
                ),
            },
            domain_names=[hostname],
            certificate=certificate,
            default_root_object="index.html",
            error_responses=[
                # S3 returns 403 for missing objects in a private bucket.
                # Map to 200/index.html so the SPA handles routing.
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                ),
            ],
            enable_logging=True,
            log_bucket=logs_bucket,
            log_file_prefix="cf-logs/",
            minimum_protocol_version=cloudfront.SecurityPolicyProtocol.TLS_V1_2_2021,
        )

        # ── GitHub Actions OIDC ───────────────────────────────────────────────
        # If this account already has the GitHub OIDC provider from another stack,
        # import it instead: iam.OpenIdConnectProvider.from_open_id_connect_provider_arn(...)
        github_provider = iam.OpenIdConnectProvider(
            self,
            "GitHubOIDCProvider",
            url="https://token.actions.githubusercontent.com",
            client_ids=["sts.amazonaws.com"],
        )

        deploy_role = iam.Role(
            self,
            "DeployRole",
            role_name="liikennevirta-deploy",
            assumed_by=iam.WebIdentityPrincipal(
                github_provider.open_id_connect_provider_arn,
                conditions={
                    "StringLike": {
                        # Restrict to pushes on the main branch only.
                        "token.actions.githubusercontent.com:sub": (
                            f"repo:{github_repo}:ref:refs/heads/main"
                        ),
                    },
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                    },
                },
            ),
            description="Assumed by GitHub Actions to deploy this stack",
        )

        # ── Deploy role permissions ───────────────────────────────────────────
        # The role does not create AWS resources directly. It delegates resource
        # creation to the CDK bootstrap roles (which CloudFormation assumes), and
        # only needs direct permissions for the S3 sync and CF invalidation steps.
        #
        # CDK bootstrap uses the qualifier "hnb659fds" by default. If you
        # bootstrapped with a custom --qualifier, update this value.
        _q = "hnb659fds"
        _acct = self.account

        # Allow CDK CLI to read the bootstrap version from SSM in both regions.
        deploy_role.add_to_policy(iam.PolicyStatement(
            sid="CdkBootstrapLookup",
            actions=["ssm:GetParameter"],
            resources=[
                f"arn:aws:ssm:eu-north-1:{_acct}:parameter/cdk-bootstrap/{_q}/version",
                f"arn:aws:ssm:us-east-1:{_acct}:parameter/cdk-bootstrap/{_q}/version",
            ],
        ))

        # Allow CDK CLI to assume the bootstrap-managed roles that do the actual
        # CloudFormation work and asset publishing.
        deploy_role.add_to_policy(iam.PolicyStatement(
            sid="CdkBootstrapRoles",
            actions=["sts:AssumeRole"],
            resources=[
                f"arn:aws:iam::{_acct}:role/cdk-{_q}-deploy-role-{_acct}-eu-north-1",
                f"arn:aws:iam::{_acct}:role/cdk-{_q}-deploy-role-{_acct}-us-east-1",
                f"arn:aws:iam::{_acct}:role/cdk-{_q}-file-publishing-role-{_acct}-eu-north-1",
                f"arn:aws:iam::{_acct}:role/cdk-{_q}-file-publishing-role-{_acct}-us-east-1",
                f"arn:aws:iam::{_acct}:role/cdk-{_q}-lookup-role-{_acct}-eu-north-1",
                f"arn:aws:iam::{_acct}:role/cdk-{_q}-lookup-role-{_acct}-us-east-1",
            ],
        ))

        # Allow the workflow to read raw data from the data bucket during build.
        deploy_role.add_to_policy(iam.PolicyStatement(
            sid="DataBucketRead",
            actions=["s3:ListBucket", "s3:GetBucketLocation"],
            resources=[data_bucket.bucket_arn],
        ))
        deploy_role.add_to_policy(iam.PolicyStatement(
            sid="DataBucketObjects",
            actions=["s3:GetObject"],
            resources=[data_bucket.arn_for_objects("*")],
        ))

        # Allow the workflow to sync static files to the site bucket.
        deploy_role.add_to_policy(iam.PolicyStatement(
            sid="SiteBucketSync",
            actions=["s3:ListBucket", "s3:GetBucketLocation"],
            resources=[site_bucket.bucket_arn],
        ))
        deploy_role.add_to_policy(iam.PolicyStatement(
            sid="SiteBucketObjects",
            actions=["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
            resources=[site_bucket.arn_for_objects("*")],
        ))

        # Allow the workflow to invalidate the CloudFront cache after each deploy.
        deploy_role.add_to_policy(iam.PolicyStatement(
            sid="CloudFrontInvalidation",
            actions=["cloudfront:CreateInvalidation"],
            resources=[f"arn:aws:cloudfront::{_acct}:distribution/*"],
        ))

        # ── Outputs ───────────────────────────────────────────────────────────
        CfnOutput(self, "DataBucketName", value=data_bucket.bucket_name)
        CfnOutput(self, "DistributionId", value=distribution.distribution_id)
        CfnOutput(self, "DistributionDomain", value=distribution.distribution_domain_name)
        CfnOutput(self, "SiteBucketName", value=site_bucket.bucket_name)
        CfnOutput(self, "LogsBucketName", value=logs_bucket.bucket_name)
        CfnOutput(self, "DeployRoleArn", value=deploy_role.role_arn)
        CfnOutput(
            self,
            "CnameTarget",
            value=distribution.distribution_domain_name,
            description=f"Add a CNAME record: {hostname} → this value",
        )
