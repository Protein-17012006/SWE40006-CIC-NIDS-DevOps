# CIC-NIDS Dashboard and DevOps Pipeline

SWE40006 Software Deployment and Evolution, team project.

A Streamlit dashboard that turns the [CSE-CIC-IDS2018](https://www.unb.ca/cic/datasets/ids-2018.html) network-intrusion dataset, and any later dataset, into six pages of charts, and the DevOps pipeline that ships it. One Docker image runs both the dashboard and the ingestion job. GitHub Actions builds it once per commit and promotes it through four environments on Amazon ECS (Fargate): development, test and staging automatically, production after a manual approval.

## Stack

| Concern | Tools |
| --- | --- |
| Application | Python 3.12, Streamlit, Plotly |
| Data | pandas, pandera, Parquet on Amazon S3, PostgreSQL 16 on Amazon RDS, SQLAlchemy, Alembic |
| Delivery | GitHub Actions, Docker, Amazon ECR, Amazon ECS on Fargate, Application Load Balancer |
| Infrastructure as code | AWS CloudFormation |
| Operations | Amazon CloudWatch, Amazon SNS, AWS Budgets |

## Environments

| Environment | URL |
| --- | --- |
| production | http://cicnids-1239707461.us-east-1.elb.amazonaws.com/ |
| staging | http://cicnids-1239707461.us-east-1.elb.amazonaws.com:8080 |
| test | http://cicnids-1239707461.us-east-1.elb.amazonaws.com:8081 |
| development | http://cicnids-1239707461.us-east-1.elb.amazonaws.com:8082 |

The [runbook](docs/runbook.md) covers setup, releases, rollback, stopping environments and teardown. The [build design](docs/design/2026-10-31-build-design.md) explains the architecture.

## Run it locally

The app runs on a laptop with no AWS account. You need Docker Desktop, and Python 3.12 for the tests.

Whole stack in containers:

```bash
docker compose up -d --build                         # PostgreSQL 16 and the dashboard
docker compose run --rm app python -m pipeline migrate
```

Open http://localhost:8501. The Pipeline page should show Database "Connected".

For development and tests, use a virtual environment outside OneDrive:

```powershell
py -3.12 -m venv $HOME\.venvs\cicnids
& $HOME\.venvs\cicnids\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
pip install -e .
docker compose up -d db
$env:TEST_ADMIN_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/postgres"
pytest                                               # database tests skip without that variable
$env:DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/cicnids"
streamlit run app/main.py
```

`.env.example` lists every setting the app reads. Copy it to `.env` for docker compose; `.env` is git-ignored.

## Status

Milestone 1 (walking skeleton) is live: the app shell runs in all four environments, deployed by the pipeline with a production approval gate. Next: data ingestion (milestone 2), then the dashboard pages.
