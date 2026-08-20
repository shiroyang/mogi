#!/usr/bin/env python3
"""mogi infrastructure — one CDK stack, everything tagged auto-delete: no.

CloudFront serves the static UI from S3 and proxies /api/* to an HTTP API backed
by the API Lambda; the API Lambda invokes the judge Lambda asynchronously; state
lives in one DynamoDB table. Total idle cost ≈ pennies/month: nothing here is
always-on compute.
"""
import aws_cdk as cdk
from aws_cdk import (
    Duration, RemovalPolicy,
    aws_apigatewayv2 as apigw,
    aws_apigatewayv2_integrations as integrations,
    aws_cloudfront as cf,
    aws_cloudfront_origins as origins,
    aws_dynamodb as ddb,
    aws_iam as iam,
    aws_lambda as lam,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    aws_ssm as ssm,
)
from constructs import Construct

ACCOUNT = "711387111223"
REGION = "eu-west-1"
GITHUB_LOGIN = "shiroyang"
SYNC_REPO = "shiroyang/oj-solutions"


class MogiStack(cdk.Stack):
    def __init__(self, scope: Construct, cid: str, **kw):
        super().__init__(scope, cid, **kw)

        table = ddb.Table(
            self, "Table",
            table_name="mogi",
            partition_key=ddb.Attribute(name="pk", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="sk", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="expires",
            removal_policy=RemovalPolicy.RETAIN,
        )
        table.add_global_secondary_index(
            index_name="gsi1",
            partition_key=ddb.Attribute(name="gsi1pk", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="gsi1sk", type=ddb.AttributeType.STRING),
            projection_type=ddb.ProjectionType.INCLUDE,
            non_key_attributes=["verdict", "prob", "mode", "ms"],
        )

        judge_fn = lam.Function(
            self, "Judge",
            function_name="mogi-judge",
            runtime=lam.Runtime.PYTHON_3_13,
            code=lam.Code.from_asset("../backend/judge"),
            handler="handler.lambda_handler",
            memory_size=1024,
            timeout=Duration.seconds(60),
            environment={"TABLE": table.table_name},
            description="mogi: sandboxed submission runner",
        )
        table.grant_read_write_data(judge_fn)

        api_fn = lam.Function(
            self, "Api",
            function_name="mogi-api",
            runtime=lam.Runtime.PYTHON_3_13,
            code=lam.Code.from_asset("../backend/api"),
            handler="handler.lambda_handler",
            memory_size=1024,
            timeout=Duration.seconds(29),
            environment={
                "TABLE": table.table_name,
                "JUDGE_FN": judge_fn.function_name,
                "PARAM_PREFIX": "/mogi",
            },
            description="mogi: API + GitHub OAuth + solution sync",
        )
        table.grant_read_write_data(api_fn)
        judge_fn.grant_invoke(api_fn)
        api_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["ssm:GetParameter", "ssm:PutParameter"],
            resources=[f"arn:aws:ssm:{REGION}:{ACCOUNT}:parameter/mogi/*"],
        ))

        http_api = apigw.HttpApi(
            self, "HttpApi", api_name="mogi",
            default_integration=integrations.HttpLambdaIntegration("ApiInt", api_fn),
        )

        site = s3.Bucket(
            self, "Site",
            bucket_name=f"mogi-site-{ACCOUNT}-{REGION}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # The API Lambda needs the viewer-facing host for the OAuth redirect_uri,
        # but CloudFront must send API Gateway's own Host to route the request —
        # so a viewer-request function stashes the real host in x-forwarded-host.
        xfh = cf.Function(
            self, "XForwardedHost",
            code=cf.FunctionCode.from_inline(
                "function handler(event) {\n"
                "  var r = event.request;\n"
                "  r.headers['x-forwarded-host'] = {value: r.headers.host.value};\n"
                "  return r;\n"
                "}"
            ),
        )

        dist = cf.Distribution(
            self, "Dist",
            comment="mogi — 真題 online judge",
            default_root_object="index.html",
            price_class=cf.PriceClass.PRICE_CLASS_100,
            default_behavior=cf.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(site),
                viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cf.CachePolicy.CACHING_OPTIMIZED,
            ),
            additional_behaviors={
                "/api/*": cf.BehaviorOptions(
                    origin=origins.HttpOrigin(
                        f"{http_api.api_id}.execute-api.{REGION}.amazonaws.com"),
                    viewer_protocol_policy=cf.ViewerProtocolPolicy.HTTPS_ONLY,
                    cache_policy=cf.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cf.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                    allowed_methods=cf.AllowedMethods.ALLOW_ALL,
                    function_associations=[cf.FunctionAssociation(
                        function=xfh,
                        event_type=cf.FunctionEventType.VIEWER_REQUEST,
                    )],
                ),
            },
        )

        s3deploy.BucketDeployment(
            self, "DeploySite",
            sources=[s3deploy.Source.asset("../web")],
            destination_bucket=site,
            distribution=dist,
            distribution_paths=["/*"],
        )

        ssm.StringParameter(self, "AllowedLogin", parameter_name="/mogi/allowed-github-login",
                            string_value=GITHUB_LOGIN)
        ssm.StringParameter(self, "SyncRepo", parameter_name="/mogi/sync-repo",
                            string_value=SYNC_REPO)

        cdk.CfnOutput(self, "SiteURL", value=f"https://{dist.distribution_domain_name}")
        cdk.CfnOutput(self, "OAuthCallbackURL",
                      value=f"https://{dist.distribution_domain_name}/api/auth/callback")
        cdk.CfnOutput(self, "TableName", value=table.table_name)
        cdk.CfnOutput(self, "JudgeFunction", value=judge_fn.function_name)


app = cdk.App()
MogiStack(app, "mogi", env=cdk.Environment(account=ACCOUNT, region=REGION))
cdk.Tags.of(app).add("auto-delete", "no")
cdk.Tags.of(app).add("project", "mogi")
app.synth()
