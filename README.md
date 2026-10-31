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

## Status

Work in progress: the repository is being scaffolded.
