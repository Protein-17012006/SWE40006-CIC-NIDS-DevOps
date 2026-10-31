"""The parts of the stacks the ingestion job depends on; cfn-lint checks the rest."""

import json
from pathlib import Path

from cfnlint.decode.cfn_yaml import load

INFRA = Path(__file__).resolve().parents[2] / "infra"


def resources(template: str = "environment.yaml") -> dict:
    return load(str(INFRA / template))["Resources"]


def policy(role: dict, name: str) -> list[dict]:
    policies = role["Properties"]["Policies"]
    return next(p for p in policies if p["PolicyName"] == name)["PolicyDocument"]["Statement"]


def test_ingest_rule_runs_the_job_with_the_object_key():
    rule = resources()["IngestRule"]["Properties"]
    assert rule["EventPattern"]["source"] == ["aws.s3"]
    assert rule["EventPattern"]["detail-type"] == ["Object Created"]
    assert rule["EventPattern"]["detail"]["bucket"]["name"] == [{"Ref": "Bucket"}]
    assert rule["EventPattern"]["detail"]["object"]["key"] == [{"prefix": "raw/"}]
    target = rule["Targets"][0]
    assert target["InputTransformer"]["InputPathsMap"] == {"key": "$.detail.object.key"}
    template = target["InputTransformer"]["InputTemplate"]
    rendered = template.replace("<key>", 'raw/my capture \\"1\\".csv')
    assert json.loads(rendered) == {
        "containerOverrides": [
            {
                "name": "job",
                "command": [
                    "python",
                    "-m",
                    "pipeline",
                    "ingest",
                    "--key",
                    'raw/my capture "1".csv',
                ],
            }
        ]
    }
    ecs = target["EcsParameters"]
    assert ecs["TaskDefinitionArn"] == {"Ref": "JobTaskDefinition"}
    assert (ecs["LaunchType"], ecs["TaskCount"]) == ("FARGATE", 1)
    assert ecs["NetworkConfiguration"]["AwsVpcConfiguration"]["AssignPublicIp"] == "ENABLED"
    assert target["RoleArn"] == {"Fn::GetAtt": ["EventsRole", "Arn"]}


def test_events_role_may_run_only_this_environments_job():
    statements = policy(resources()["EventsRole"], "run-ingestion-job")
    run_task = next(s for s in statements if s["Action"] == "ecs:RunTask")
    assert run_task["Resource"] == {
        "Fn::Sub": (
            "arn:${AWS::Partition}:ecs:${AWS::Region}:${AWS::AccountId}"
            ":task-definition/cicnids-${EnvName}-job:*"
        )
    }
    assert "ArnEquals" in run_task["Condition"]
    pass_role = next(s for s in statements if s["Action"] == "iam:PassRole")
    assert pass_role["Resource"] == [
        {"Fn::GetAtt": ["ExecutionRole", "Arn"]},
        {"Fn::GetAtt": ["TaskRole", "Arn"]},
    ]


def test_task_role_may_delete_only_processed_objects():
    statements = policy(resources()["TaskRole"], "own-bucket")
    deletes = [s for s in statements if "s3:DeleteObject" in str(s["Action"])]
    assert deletes == [
        {
            "Effect": "Allow",
            "Action": "s3:DeleteObject",
            "Resource": {"Fn::Sub": "${Bucket.Arn}/processed/*"},
        }
    ]


def test_databases_keep_seven_days_of_backups():
    for name in ("ProdDatabase", "NonprodDatabase"):
        assert resources("databases.yaml")[name]["Properties"]["BackupRetentionPeriod"] == 7
