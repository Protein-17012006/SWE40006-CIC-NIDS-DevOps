# Runbook

How to set up, release, roll back, pause and tear down the CIC-NIDS pipeline. Everything runs in AWS account 551169294418 (CLI profile `hoang`), region us-east-1.

## Environments

| Environment | URL | Cluster | Deployed |
| --- | --- | --- | --- |
| development | http://cicnids-1239707461.us-east-1.elb.amazonaws.com:8082 | cicnids-nonprod | automatically on every merge to main |
| test | http://cicnids-1239707461.us-east-1.elb.amazonaws.com:8081 | cicnids-nonprod | automatically after development |
| staging | http://cicnids-1239707461.us-east-1.elb.amazonaws.com:8080 | cicnids-nonprod | automatically after test |
| production | http://cicnids-1239707461.us-east-1.elb.amazonaws.com/ | cicnids-prod | after a reviewer approves in GitHub |

The Pipeline page of each environment shows its name, the image tag it runs (the 7-character commit hash) and whether it reaches its database.

## First-time setup

These steps were done once on 31 October 2026; repeat them only for a new account or a new repository.

1. Deploy the bootstrap stack from a laptop. It is the only stack not deployed by GitHub Actions, because it creates the roles GitHub Actions uses.

   ```bash
   export AWS_PROFILE=hoang
   aws cloudformation deploy --template-file infra/bootstrap.yaml --stack-name cicnids-bootstrap \
     --capabilities CAPABILITY_NAMED_IAM --tags Project=cic-nids Environment=shared --region us-east-1
   ```

   The roles trust GitHub's immutable OIDC subjects, which carry the owner and repository ids. For another repository, pass its prefix as `GitHubSubjectPrefix`: `gh api repos/OWNER/REPO/actions/oidc/customization/sub --jq .sub_claim_prefix`.
2. In GitHub, set the secret `AWS_ACCOUNT_ID` (a secret, so public logs mask it) and the variable `AWS_REGION=us-east-1`. The variable `ALERT_EMAIL` is optional; when set, the platform stack subscribes it to the alerts topic.
3. Create the environments development, test and staging without rules, and production and platform with a required reviewer.
4. Run the Infrastructure workflow and approve `platform`. It creates `cicnids-platform`, then `cicnids-databases` (about 15 minutes).
5. Run the CD workflow. The first run creates each environment stack, its database role and database, and runs the migrations.
6. Protect main: pull request required, checks `lint`, `test`, `cfn-lint` and `image` required, branch up to date, no force pushes.

## How a release flows

1. Open a pull request. CI runs lint, tests with coverage, cfn-lint, and a Docker build with a Trivy scan. A pull request that touches the shared templates also gets a change-set preview in its Infrastructure run summary.
2. Merge when the checks are green. CD builds the image once, tags it with the commit hash and pushes it to ECR.
3. For each environment, `scripts/ci/deploy_env.sh` updates the stack with the new job image, runs `db-bootstrap` and the migrations as one-off ECS tasks, updates the stack with the new app image, runs the smoke test, and starts `reconcile` without waiting for it.
4. Development, test and staging deploy in turn. Production waits in the CD run until a reviewer opens it, chooses **Review deployments** and approves `production`. The production job then writes a parity table: the tag each environment runs.

Changes to `docs/` or Markdown files do not start CD. Changes to the shared templates start the Infrastructure workflow, which waits for approval in `platform`.

## Roll back

Run the **Rollback** workflow with the environment and the earlier tag. It redeploys that image without migrations; migrations only add before they remove, so an older image keeps working against the newer schema. The run summary lists the newest ten tags. Production still needs approval.

A rollback also skips `reconcile`, and the upload rule then starts the older image's job. An image older than milestone 2 (2a5a429 and before) has no `ingest` command, so upload nothing to `raw/` while an environment runs one.

A CD run that waits at the production gate holds the production deployment lock, so a Rollback run started after it stays pending. Open the CD run, choose **Review deployments** and reject `production` first.

The drill on 31 October 2026 rolled production back from 336613d to 2a5a429 in 6 min 54 s, from approval to a passing smoke test, and forward to 4e8d1a7 in 7 min.

## Load data

Each environment's bucket is `cicnids-<env>-<account id>`. A CSV that lands in `raw/` starts the job task within a minute or two, through the EventBridge rule `cicnids-<env>-ingest`. The job reads the file in 100,000-row chunks, cleans it, and then either loads it or quarantines it:

- **Loaded.** Cleaned rows go to `processed/<dataset>/<file>/part-NNNN.parquet`; aggregates and a sample go to PostgreSQL.
- **Quarantined.** No contract matches the header, more than 20% of the rows fail validation, or the file has no rows. The report and a draft contract go to `quarantine/<dataset>/<file>/`, and the CSV stays in `raw/`.

The dataset is the first folder under `raw/` (`raw/cse-cic-ids2018/<day>.csv`), or the file's own name when it sits directly in `raw/`. Keys may contain spaces: the rule passes the key exactly as it was uploaded.

**The baseline.** Run this from the laptop. It copies the files one at a time and waits for each ingestion run, with the 4 GB file last; it skips any file already in `raw/`, so it can be run again after an interruption.

```bash
export AWS_PROFILE=hoang
scripts/load_baseline.sh development   # the first 100,000 rows of 14 February
scripts/load_baseline.sh staging       # the ten day files, about 25 minutes
scripts/load_baseline.sh production
```

On 31 October 2026, each environment's load took about 25 minutes. It yielded 15,822,222 flows: 16,233,002 rows read, with exact duplicates and repeated header rows dropped and 14 rows rejected. The 4 GB day file took 5 to 6 minutes in one job task. PostgreSQL holds about 47 MB of aggregates and samples.

**Simulated real traffic.** Download one day file and derive the simulated file from it. Write it outside the repository: full files are never committed.

```bash
aws s3 cp --no-sign-request "s3://cse-cic-ids2018/Processed Traffic Data for ML Algorithms/Friday-16-02-2018_TrafficForML_CICFlowMeter.csv" /tmp/friday-16.csv
python -m scripts.make_simulated /tmp/friday-16.csv /tmp/simulated-real-traffic-01.csv
aws s3 cp /tmp/simulated-real-traffic-01.csv s3://cicnids-staging-<account id>/raw/simulated-real-traffic-01.csv
```

**The Ingest workflow.** Run it with an environment and one of three targets: an S3 key under `raw/` ingests that file again; `reconcile` re-ingests every file whose stored header now matches a different contract or contract version; `status` logs each dataset's status, row count and files, and the size of each table. Production waits for approval. The run prints the job's log, in which every run is one `ingestion_run` line.

## Demo: merge the simulated contract

The simulated file starts out quarantined, because no contract in `contracts/` matches it. During the demo:

1. Download `quarantine/simulated-real-traffic-01/simulated-real-traffic-01/draft-contract.yaml` and save it as `contracts/simulated-real-traffic.yaml`. It is the same as `tests/fixtures/contracts/simulated-real-traffic.yaml`.
2. Move `tests/contracts/broken/simulated-real-traffic-01.csv` to `tests/contracts/simulated-real-traffic/`, and delete its entry in `tests/contracts/broken/expected.yaml`.
3. Open a pull request. The contract tests check that the sample now matches its contract.
4. After the merge, each deployment starts `reconcile`, which loads the quarantined file without a new upload. Label-based charts are hidden for it, because the file has no label.

## Stop and start environments by hand

Stopping a service stops its Fargate cost; the load balancer and RDS keep running.

```bash
export AWS_PROFILE=hoang
aws ecs update-service --cluster cicnids-nonprod --service cicnids-staging --desired-count 0
aws ecs update-service --cluster cicnids-nonprod --service cicnids-staging --desired-count 1
```

A deployment to a stopped environment starts one task first, so its smoke test has something to check. RDS instances can also be stopped for up to seven days (`aws rds stop-db-instance --db-instance-identifier cicnids-nonprod`).

## Account limits met on the way

- New repositories sign OIDC tokens with immutable subjects; trust policies must use `repo:OWNER@ID/REPO@ID:...`.
- An AWS free account plan rejects RDS backups longer than one day and allows two RDS instances at a time, counting instances that are still being deleted. The project account is on the paid plan, so the templates keep seven days of backups.
- A stack whose first creation fails is left in ROLLBACK_COMPLETE; the deploy scripts delete such an empty stack before retrying.

## Tear everything down after grading

Delete in this order, because each stack imports from the ones after it. Empty the environment buckets first.

```bash
export AWS_PROFILE=hoang
for env in development test staging production; do
  aws s3 rm "s3://cicnids-$env-551169294418" --recursive
  aws cloudformation delete-stack --stack-name "cicnids-$env"
done
# wait for the four deletions, then:
aws cloudformation delete-stack --stack-name cicnids-databases   # keeps a final snapshot of each RDS instance
aws cloudformation delete-stack --stack-name cicnids-platform    # empties the ECR repository
aws cloudformation delete-stack --stack-name cicnids-bootstrap
```

Delete the final RDS snapshots too, once nobody needs the data: `aws rds describe-db-snapshots --snapshot-type manual`.
