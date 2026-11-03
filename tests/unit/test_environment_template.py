"""The parts of the stacks the ingestion job depends on; cfn-lint checks the rest."""

import json
import re
from pathlib import Path

import pytest
from cfnlint.decode.cfn_yaml import load

INFRA = Path(__file__).resolve().parents[2] / "infra"
REPO = INFRA.parent


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


DEPLOY_ROLES = {
    "DeployRoleDevelopment": ("development", "cicnids-nonprod"),
    "DeployRoleTest": ("test", "cicnids-nonprod"),
    "DeployRoleStaging": ("staging", "cicnids-nonprod"),
    "DeployRoleProduction": ("production", "cicnids-prod"),
}


def _actions(statement: dict) -> list[str]:
    action = statement.get("Action", [])
    return [action] if isinstance(action, str) else list(action)


@pytest.mark.parametrize("role", sorted(DEPLOY_ROLES))
def test_deploy_role_may_start_only_its_own_database(role):
    env_name, instance = DEPLOY_ROLES[role]
    statements = policy(resources("bootstrap.yaml")[role], f"deploy-{env_name}")
    rds = [s for s in statements if any(a.startswith("rds:") for a in _actions(s))]
    assert len(rds) == 1
    assert sorted(_actions(rds[0])) == ["rds:DescribeDBInstances", "rds:StartDBInstance"]
    assert rds[0]["Resource"] == {
        "Fn::Sub": f"arn:${{AWS::Partition}}:rds:${{AWS::Region}}:${{AWS::AccountId}}:db:{instance}"
    }


def test_no_role_may_stop_a_database():
    text = (INFRA / "bootstrap.yaml").read_text(encoding="utf-8")
    assert "rds:Stop" not in text and "rds:*" not in text


ALARMS = {
    "ServerErrorsAlarm": "5xx",
    "CpuAlarm": "cpu",
    "MemoryAlarm": "memory",
    "UnhealthyTargetsAlarm": "unhealthy-targets",
    "FailedIngestionAlarm": "failed-ingestion",
}
TOPIC = {"Fn::ImportValue": {"Fn::Sub": "${PlatformStack}-AlertTopicArn"}}


@pytest.mark.parametrize("name", sorted(ALARMS))
def test_alarm_emails_and_ignores_stopped_environments(name):
    p = resources()[name]["Properties"]
    assert p["AlarmName"] == {"Fn::Sub": f"cicnids-${{EnvName}}-{ALARMS[name]}"}
    assert p["AlarmActions"] == [TOPIC] and p["OKActions"] == [TOPIC]
    assert p["TreatMissingData"] == "notBreaching"


def test_cpu_and_memory_thresholds_are_the_briefs():
    r = resources()
    assert r["CpuAlarm"]["Properties"]["Threshold"] == 80
    assert r["MemoryAlarm"]["Properties"]["Threshold"] == 85


def test_metric_filters_read_events_the_code_logs():
    from pipeline.cli import COMMANDS

    filters = [
        r["Properties"] for r in resources().values() if r["Type"] == "AWS::Logs::MetricFilter"
    ]
    names = {f["MetricTransformations"][0]["MetricName"] for f in filters}
    assert names == {"PageRenderTime", "IngestionDuration", "RejectedRows", "FailedIngestions"}
    events = {
        e for f in filters for e in re.findall(r'\$\.event = "([a-z_-]+)"', f["FilterPattern"])
    }
    assert events <= {"page_render", "ingestion_run", *COMMANDS}
    assert '"page_render"' in (REPO / "app/telemetry.py").read_text(encoding="utf-8")
    assert '"ingestion_run"' in (REPO / "pipeline/ingest.py").read_text(encoding="utf-8")


def test_dashboard_shows_what_the_brief_lists():
    body = resources()["Dashboard"]["Properties"]["DashboardBody"]["Fn::Sub"]
    text = body[0] if isinstance(body, list) else body
    widgets = json.loads(re.sub(r"\$\{[^}]+\}", "x", text))["widgets"]
    assert [w["properties"]["title"] for w in widgets] == [
        "Requests",
        "Latency",
        "Errors",
        "CPU and memory",
        "Network in and out",
        "Targets",
        "Page render time",
        "Ingestion",
        "Failed ingestions",
        "Alarms",
    ]


def test_alert_email_stays_hidden():
    assert load(str(INFRA / "platform.yaml"))["Parameters"]["AlertEmail"]["NoEcho"] is True
    workflow = (REPO / ".github/workflows/infra.yml").read_text(encoding="utf-8")
    assert "secrets.ALERT_EMAIL" in workflow and "vars.ALERT_EMAIL" not in workflow
