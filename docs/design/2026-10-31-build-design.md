# Build design: CIC-NIDS dashboard and pipeline

Approved by Hoàng on 31 October 2026, with the answers recorded in section 1

This design fixes what the team needs to build the whole system in this repository. The requirements document (ING, UI, NFR and OPS requirements) and the Design and Requirements Report (app and UI design) remain the source of truth. This document covers what they leave open: the ingestion job, the AWS infrastructure, the pipeline, and the five open questions in section 8 of the report. Section 1 lists what Hoàng decided; everything else is the builder's call and can change on review.

## 1. Decisions already taken

| Decision | Decided by |
| --- | --- |
| One team builds everything here: dashboard, ingestion and contracts, schema, CloudFormation, workflows and monitoring. The split in report section 1.5 (dashboard by Thiên Anh) no longer applies. | Hoàng, 31 Oct |
| Every resource lives in us-east-1. | Hoàng, 31 Oct; brief |
| The code lives in the public repository Protein-17012006/SWE40006-CIC-NIDS-DevOps. | Hoàng, 31 Oct; brief |
| Four environments on ECS Fargate behind one load balancer; CloudFormation; GitHub Actions signing in through OIDC; CloudWatch; USD 200 of credit. | Brief |
| Pull requests merge once CI is green; no approving review is required. Production still waits for an approval in its GitHub environment (OPS-03). | Hoàng, 31 Oct |
| No alert email for now. The SNS topic and the budget exist, and an email subscription is an optional stack parameter. | Hoàng, 31 Oct |
| Hoàng stops and starts environments by hand to control cost, so there is no scheduled scale-to-zero (OPS-08 is dropped for now). | Hoàng, 31 Oct |

## 2. Goals, non-goals and anti-goals

**Goal.** Every item of the demo checklist works live, first in staging and then in production. All 25 Must requirements are met, Should requirements as time allows, and total AWS spend stays under USD 200 (aim: under 150).

**Non-goals.** As in brief section 5.2: no sign-in, HTTPS or custom domain, machine learning, multi-region, blue/green releases, or Prometheus.

**Anti-goals.** These count as failures even if the demo runs:

- Deploying anything by hand in the console. CloudFormation creates every resource and GitHub Actions makes every change; the one-time bootstrap stack is the only exception.
- Anything secret in the public repository, including the alert email address.
- A page that reads raw files or names a source column.
- Credit spent on idle or forgotten resources. Every resource carries the tag `Project=cic-nids`; resources without it belong to other course work in this account and are never touched.

## 3. AWS infrastructure

### 3.1 Stacks

| Stack | Template | What it holds | Deployed by |
| --- | --- | --- | --- |
| cicnids-bootstrap | infra/bootstrap.yaml | GitHub OIDC provider; GitHub Actions roles (build, change-set preview, platform, one deploy role per environment); the CloudFormation execution role | Hoàng, once, from a laptop |
| cicnids-platform | infra/platform.yaml | VPC 10.20.0.0/16 over two Availability Zones (two public and two private subnets, internet gateway, S3 gateway endpoint, no NAT gateway); the load balancer and its security group; ECR repository `cic-nids`; ECS clusters `cicnids-prod` and `cicnids-nonprod`; SNS topic `cicnids-alerts` with an optional email subscription; a USD 200 budget whose alerts at 50, 100 and 150 publish to that topic | infra.yml |
| cicnids-databases | infra/databases.yaml | Two RDS PostgreSQL 16 db.t4g.micro instances, production and non-production (shared by development, test and staging); 20 GB gp3, single-AZ, private subnets; master passwords managed by RDS in Secrets Manager; 1-day backups (the AWS free account plan rejects longer); snapshot on delete | infra.yml |
| cicnids-&lt;env&gt;, one per environment | infra/environment.yaml with infra/params/&lt;env&gt;.json | S3 bucket; secrets; task, execution and EventBridge roles; log group; security group and its RDS ingress rule; target group and listener; job, admin and app task definitions; ECS service; EventBridge rule; metric filters, alarms and dashboard | deploy.yml, on every release |

The databases have their own stack, so no platform or environment change can replace them. The environment template changes through the same promotion as code: an edit reaches development first and production last.

### 3.2 Environments

| Environment | Cluster | Port | App task | Database (instance / name) | Data |
| --- | --- | --- | --- | --- | --- |
| development | cicnids-nonprod | 8082 | 0.25 vCPU, 1 GB | non-production / cicnids_development | One day file cut to 100,000 rows |
| test | cicnids-nonprod | 8081 | 0.25 vCPU, 1 GB | non-production / cicnids_test | End-to-end files of every known format, reset on each run |
| staging | cicnids-nonprod | 8080 | 0.5 vCPU, 1 GB | non-production / cicnids_staging | Full CSE-CIC-IDS2018 |
| production | cicnids-prod | 80 | 0.5 vCPU, 1 GB | production / cicnids_production | Full baseline plus simulated real-traffic files |

The job task (ingestion, migrations, end-to-end tests) has 2 vCPU, 8 GB and 20 GB of ephemeral storage. The admin task (database bootstrap) has 0.25 vCPU and 0.5 GB. Container Insights is on for `cicnids-prod` only, behind a platform parameter: it is the largest CloudWatch cost, and the Level 2 evidence needs it only for production.

### 3.3 Network and security

- App and job tasks run in public subnets with public IP addresses, so they reach ECR, S3, Secrets Manager and CloudWatch without a NAT gateway, which would cost about USD 33 a month plus data. App security groups accept port 8501 only from the load balancer; job tasks accept no inbound traffic.
- RDS sits in private subnets with no public endpoint. Each environment stack adds one ingress rule to its RDS security group for its own tasks, so production RDS accepts only production tasks (NFR-03).
- Each environment has its own task role, execution role and secrets. The task role reaches only its own bucket and may run only its own job task definition (for Re-ingest). The execution role pulls from ECR, reads its own secrets and writes its log group. The secrets are `cicnids/<env>/db` (username, generated password, host, port, database name) and `cicnids/<env>/upload-password`.
- GitHub Actions signs in through OIDC only; no AWS keys are stored in GitHub. The build role trusts workflow runs on this repository's branches. Each deploy role trusts only its GitHub environment (`repo:Protein-17012006@193206418/SWE40006-CIC-NIDS-DevOps@1440630321:environment:<env>`; the repository uses GitHub's immutable subjects, which carry the owner and repository ids) and may update only its own stack, pass the CloudFormation execution role, run its own job and admin tasks, and read their logs.
- The CloudFormation execution role has AdministratorAccess, and only CloudFormation can assume it, the pattern CDK bootstrap uses. Templates stay simple, and no person or workflow holds the broad role directly.

### 3.4 Application settings

The deployment contract in report section 3.3 holds, with one change. ECS injects the environment's database secret as `DB_SECRET` (JSON), and `config.py` builds the SQLAlchemy URL from it when `DATABASE_URL` is not set. Laptops and CI keep setting `DATABASE_URL` directly. The reason: CloudFormation can generate a password inside a secret, but it cannot write a URL that contains that password.

## 4. Pipeline

### 4.1 Workflows

| Workflow | Trigger | What it does |
| --- | --- | --- |
| ci.yml | Pull request to main | ruff lint and format check; pytest (unit tests, page tests with AppTest on a PostgreSQL 16 service container, data-contract tests) with at least 80% line coverage on `pipeline/`; cfn-lint; Docker build and Trivy scan, failing on fixable critical or high findings. All of them are required checks (OPS-02). |
| infra.yml | Pull request or push that touches the bootstrap, platform or databases templates; manual | On a pull request: creates change sets and writes them to the job summary without executing them. On main: deploys cicnids-platform and cicnids-databases after approval in the `platform` environment. |
| cd.yml | Push to main (docs-only changes skipped); manual run on any branch, development only | Builds the image once, tags it with the 7-character commit hash and pushes it to ECR. Calls deploy.yml for development, test, staging and production in turn (OPS-03), then writes a table of the tag each environment runs. |
| deploy.yml | Called by cd.yml and rollback.yml | Deploys one tag to one environment (section 4.2). |
| rollback.yml | Manual: environment and tag | Calls deploy.yml with the earlier tag and without migrations. Its summary lists the last ten tags (OPS-05). |
| ingest.yml | Manual: environment and either an S3 key or `reconcile` | Runs the job task and prints its log (ING-01 on demand, ING-09). |

The GitHub environments development, test and staging have no reviewers; production and platform need approval from Hoàng. Branch protection on main requires a pull request and green CI checks, but no approving review.

### 4.2 One deployment

deploy.yml applies changes in the order the brief fixes: infrastructure, migrations, application, smoke test.

1. Update cicnids-&lt;env&gt; with the current template and the new `JobImageTag`, keeping `AppImageTag`. The running app is untouched.
2. Run the admin task `db-bootstrap`. It is idempotent: it creates the database and role when missing and syncs the password with the secret.
3. Run the job task `migrate` (`alembic upgrade head`) and wait. A failure stops the deployment (OPS-04).
4. Update the stack with the new `AppImageTag`. ECS replaces tasks with 100% minimum healthy, 200% maximum, a 30-second deregistration delay and a circuit breaker that rolls back (NFR-02).
5. Smoke test: the service is stable, its running task definition carries the tag, and `/_stcore/health` on the environment's port answers 200 within two minutes (OPS-07).
6. In test, run the job task `e2e` and wait for it. In the other environments, start `reconcile` without waiting.

If Hoàng stopped the service by hand, deploy.yml sets its desired count back to one first, so the smoke test always has a task to check.

## 5. Ingestion

### 5.1 Trigger, identity and folders

- Each bucket sends its events to EventBridge. A rule on Object Created under `raw/` runs the job task with `ingest --key <key>` (ING-01).
- The dataset is the first folder under `raw/`, so `raw/cse-cic-ids2018/Wednesday-14-02-2018.csv` belongs to `cse-cic-ids2018`. A file directly in `raw/` is its own dataset, named after the file (`raw/simulated-real-traffic-01.csv`).
- `raw/` is never edited. Cleaned data goes to `processed/<dataset>/<file>/part-NNNN.parquet`. A rejected file gets `quarantine/<dataset>/<file>/report.md` and `draft-contract.yaml`, while its CSV stays in `raw/`.

### 5.2 Steps for one file

1. Record the run as running, with the image's commit hash.
2. Download the CSV to ephemeral storage and read its header. Normalise the column names (trim, lower case, other characters to underscores) and pick the contract whose required fields are all present; the most matched columns wins (ING-02).
3. If no contract matches, quarantine the file (ING-03). The report names the missing required fields and the unmatched columns. The draft contract proposes a mapping for each column (an exact normalised match, then a synonym list of CICFlowMeter naming variants, then string similarity) and marks the fields it could not map as TODO (ING-08).
4. If a contract matches, stream the file in chunks of 100,000 rows read as text. For each chunk: drop repeated header rows; map columns to canonical names and coerce types, applying the contract's unit scale; replace infinities with null; trim labels; validate with pandera, rejecting and counting the failing rows; derive `attack_category` through the label map, rejecting unknown labels; keep every unmapped column in `extras`, and flag columns the contract does not know as new (ING-04, ING-07).
5. Drop exact duplicates across the whole file, using a set of 64-bit row hashes.
6. Accumulate the outputs in bounded memory: hourly and port counts; rows changed by each cleaning step; nulls, infinities, minimum and maximum per column (to find constant columns); and the sample. Each row gets a random key, and each category and day keeps the 2,000 rows with the smallest keys, so rarer classes keep every row. Write each cleaned chunk to Parquet (ING-05).
7. If more than 20% of rows were rejected, quarantine the file instead: that many failures points to a wrong contract, not to bad rows.
8. Load everything in one transaction while holding an advisory lock on the dataset. Delete this file's earlier rows from the aggregate and sample tables, insert the new ones with ports capped at the top 50 per day, category and protocol, update the dataset row and mark the run loaded (ING-05, ING-06).
9. Log one `ingestion_run` event with the duration, rows read, loaded and rejected, and the status. Any exception marks the run failed and exits with code 1 (NFR-05, OPS-06).

A 4 GB day file fits the 8 GB task, because only one chunk and the running totals are in memory at a time.

### 5.3 Re-ingestion

This resolves "Re-ingest trigger" in report section 8.

- `reconcile` re-ingests quarantined files whose stored header now matches a contract in the image, and loaded files whose contract version has changed (ING-09). deploy.yml starts it after every deployment, so a merged contract loads its file without a new upload.
- The Re-ingest button calls `storage.start_ingestion(file_key)`, which runs the environment's job task through ECS RunTask with `ingest --key`. The button stays disabled until a contract in the deployed image matches the header stored on the file's last run.

### 5.4 Data contracts

One YAML file per source sits in `contracts/`, checked by a pydantic model:

```yaml
name: cse-cic-ids2018
version: 1
timestamp_format: "%d/%m/%Y %H:%M:%S"
fields:               # canonical field: source column, with an optional unit scale
  dst_port: Dst Port
  flow_duration_us: Flow Duration
  label: Label
  # ...
known_extras: [Fwd Pkt Len Max, Init Fwd Win Byts]   # kept as extras, not flagged as new
label_map:
  Benign: Benign
  DDOS attack-HOIC: DDoS
  Infilteration: Infiltration
  # ...
```

Contract tests run each contract against its sample files in `tests/contracts/<name>/`, and check that every file in `tests/contracts/broken/` is quarantined for the expected reason.

### 5.5 Baseline and simulated files

- The baseline comes from the public bucket `s3://cse-cic-ids2018/Processed Traffic Data for ML Algorithms/`: 10 CSV files, 6.9 GB in total. The 20 February file is 4.05 GB, carries the four extra identifier columns and is spelled "Thuesday". `scripts/load_baseline` copies the files into `raw/cse-cic-ids2018/` of staging and production one at a time, so each copy starts one ingestion run.
- `scripts/make_simulated` derives the simulated real-traffic files from a baseline day: about 100,000 rows, columns renamed to CIC-IDS2017-style names ("Destination Port", "Total Fwd Packets"), two new columns (`pkt_entropy`, `geo_country`) and no label. Full files are generated, never committed; a 500-row sample is committed for the contract tests.
- In the demo, the simulated file is uploaded through the Pipeline page's upload card (ING-10) if it is built, otherwise with `aws s3 cp`.

## 6. Data design changes

Report section 4.3 stands, with these changes:

- `agg_hourly`, `agg_ports` and `flow_sample` gain `file_key`, so re-ingesting one file replaces only its rows. Pages still sum across files.
- `ingestion_runs` gains `contract_name` and `message`, one plain sentence for the Pipeline page.
- The sample and port limits stay as proposed: 2,000 flows per category per capture day, and the top 50 ports. They are defaults, to revisit after the first staging load. This resolves "Sample and port limits" in report section 8; the ingestion-owner and schema questions there are settled by section 1 and this section.

## 7. Testing

Report section 7.1 stands, with three decisions:

- **Coverage.** At least 80% line coverage on `pipeline/`, which meets both NFR-06 (70%) and the brief's quality gate (80%). This resolves "Coverage target" in report section 8.
- **End-to-end tests** run as a job task inside the test environment, the only place that can reach its private database. The task resets the test database and bucket, and uploads one file of every known format to `raw/`, so the real EventBridge path runs. It then waits for the runs, checks their status and counts, and renders every page with AppTest against the test database.
- **Load test.** Locust drives the HTTP endpoints: the page shell, static files and `/_stcore/health`. Streamlit draws pages over a WebSocket that Locust does not speak, so page speed is judged by the page-render metric (NFR-01). Locust shows request latency, and that a rolling deployment causes no 5xx responses (NFR-02).

## 8. Monitoring and cost

- **Logs.** One log group per environment, `/cicnids/<env>`, kept for 14 days, with one JSON object per line.
- **Metrics.** Metric filters turn each environment's logs into four metrics in the `CICNIDS` namespace, with an Environment dimension: page render time, ingestion duration, rejected rows and failed ingestions (NFR-05).
- **Alarms.** Each environment has alarms on the 5xx count, CPU above 80%, memory above 85%, unhealthy targets and failed ingestion. They publish to the SNS topic, which emails the team once an address is subscribed (OPS-06).
- **Dashboards.** One per environment; production's is the demo dashboard.

**Cost.** Hoàng controls spend by hand, stopping environments when they are idle. With everything running around the clock for five weeks, the estimate is about USD 180, so the USD 200 credit holds. The figure is approximate, from list prices remembered as of October 2026; Cost Explorer is the check. The largest items are Fargate (about 66), RDS (32), CloudWatch (26), public IPv4 addresses (25) and the load balancer (21). Every stack is deleted after grading (brief section 5.1).

## 9. Repository layout

`app/` follows report section 3.2. The rest of the repository:

```text
pipeline/            ingestion package: python -m pipeline <ingest | reconcile | migrate | db-bootstrap>
contracts/           YAML data contracts
migrations/          Alembic
tests/               unit/, app/, contracts/, e2e/, load/, fixtures/
infra/               bootstrap.yaml, platform.yaml, databases.yaml, environment.yaml, params/
scripts/             load_baseline, make_simulated
.github/workflows/   ci, infra, cd, deploy, rollback, ingest
docs/                this design and the runbook
```

The image holds `app/`, `pipeline/`, `contracts/`, `migrations/` and `tests/e2e/` with its files, so the same image can run the end-to-end job.

## 10. Build order

1. **Walking skeleton.** The scaffold; the app shell with the Environment, App version and Database tiles; Dockerfile, docker-compose and CI; the bootstrap, platform, databases and environment stacks; CD to all four environments with the production gate, smoke tests and rollback. This proves Levels 1, 3 and 4 with an empty dashboard.
2. **Data.** The schema migration, contracts, ingestion, the EventBridge trigger, reconcile and ingest.yml; the baseline load into staging and production; the simulated files.
3. **Pages**, in the report's order: Overview with the guard and the unlabelled state, Timeline, Targets, the rest of Pipeline, Data quality, Feature explorer.
4. **Operations.** Metric filters, alarms and dashboards checked; end-to-end tests in test; Locust; a rollback drill; a demo rehearsal; then the Could items (CSV download, upload card).
