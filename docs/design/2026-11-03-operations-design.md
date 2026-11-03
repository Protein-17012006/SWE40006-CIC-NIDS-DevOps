# Design: operations run by the pipeline

Agreed on 3 November 2026; section 1 lists what was decided then.

This design covers step 4 of the build order in the [build design](2026-10-31-build-design.md): operations. It starts from the project brief (section 3 for the levels and their evidence, section 4.1 for the success metrics, section 4.2 for the demo scenario), the Design and Requirements Report (NFR-02, NFR-05, OPS-05, OPS-06 and ING-10) and the build design (sections 4.2, 7 and 8). Neither the brief nor the report is in this repository. The build order calls this step "checked", but the metric filters, alarms, dashboards, end-to-end tests and load test were never built; this design builds them. Everything outside section 1 is a proposal the builder may change on review.

## 1. Decisions already taken

| Decision | Date |
| --- | --- |
| The demo shows one thing: once a feature is coded and its deployment starts, everything else runs by itself. Operations serves that. The pipeline checks each release, watches each environment and brings stopped parts back, with no person at the console. | 3 Nov |
| The demo follows the brief's scenario (section 4.2) as written. | 3 Nov |
| After each deployment to test, end-to-end tests run on their own. A failure stops the release before staging. | 3 Nov |
| Locust runs on its own during every staging and production deployment. Any 5xx response fails the deployment (NFR-02). | 3 Nov |
| Metric filters, alarms and dashboards live in each environment's stack, so every deployment creates or updates them. | 3 Nov |
| A deployment starts its RDS instance when the instance is stopped, then carries on. Stopping stays a manual decision. | 3 Nov |
| Rollback stays the one-run workflow. A drill on the current release measures the time to restore (target: under 10 minutes). | 3 Nov |
| Alarms email Hoàng. This replaces the 31 October decision "no alert email for now". The address stays out of the repository and out of workflow logs. | 3 Nov |
| The rehearsal runs every step of scenario 4.2 on the real environments except merging the simulated contract into main, which can happen only once. That step is rehearsed in development from a branch, as in milestone 2. | 3 Nov |
| One pull request per part, in this order: database start, monitoring and email, end-to-end tests, load test, rollback drill, the upload card if time allows, and the rehearsal last. | 3 Nov |

These still hold from earlier: production waits for Hoàng's approval in GitHub (build design section 1), and pull requests ship one at a time, the next one's CD starting only after the previous one reached production (milestone 3).

## 2. Goals, non-goals and anti-goals

**Goal.** Every remaining Must requirement is met, and the pipeline proves it on every release: NFR-05 (custom metrics on the production dashboard), OPS-06 (alarms email the team, shown with a forced failure) and NFR-02 (no 5xx while a deployment runs under load). End-to-end tests run in test, and a rollback drill restores production in under 10 minutes. The brief's evidence for Level 2 is ready: the production dashboard during a load test, with one alarm firing. Scenario 4.2 has been rehearsed. ING-10, a Could item, if time allows.

The success metrics of brief section 4.1 that this design must meet or keep:

| Metric | Target | Today |
| --- | --- | --- |
| Performance | 95% of requests answered within 2 s with 20 simulated users for 5 minutes; CPU below 80% | not measured |
| Monitoring and alerting | CPU, memory, network, requests, latency and errors for production on one dashboard; a test alarm reaches the email within 5 minutes | nothing built |
| Time to restore | the previous version back in production within 10 minutes | 6 min 54 s (31 October drill) |
| Lead time | merge to staging under 30 minutes; production within 15 minutes of approval | about 25 and 9 minutes |
| Availability | no failed requests during a release | not measured |
| Cost | total AWS spend under USD 200, aiming for under 150 | USD 5.19 before credits (2 November) |

**Non-goals.**

- Scheduled scale-to-zero (OPS-08 stays dropped), or a workflow that stops environments. Stopping stays by hand, as the runbook describes.
- Rolling back automatically when an alarm fires. ECS's circuit breaker, the smoke test and the checks in this design are enough for the course.
- Load-testing how pages render. Streamlit draws pages over a WebSocket that Locust does not speak, so NFR-01 stays judged by the page-render metric (build design section 7).
- Faster first page loads, for example by compressing Streamlit's static files or adding CloudFront.
- Changes to the pages, ingestion, contracts or schema, apart from what the end-to-end tests and the upload card need.
- Prometheus and Grafana, HTTPS, sign-in.

**Anti-goals.** These count as failures even if every check passes:

- Creating or changing anything by hand in the AWS console. The bootstrap stack, deployed from a laptop, stays the one exception.
- The alert email address anywhere in the repository, a commit message, a pull request or a public workflow log.
- A check that fails by chance. A flaky end-to-end or load check would block releases and could break the live demo. Each check fails only for a real fault, rides out brief network errors, and says in one line what failed.
- Alarm noise: email while an environment is stopped on purpose, or on routine deployments. An alarm that fires every day gets ignored.
- Releases slower than the lead-time targets above.
- Merging the simulated contract into main before the demo.
- A reset that can touch any environment other than test.
- New always-on resources. Everything added lives in CloudWatch, runs on GitHub's runners, or runs as a one-off task.

## 3. Where things stand

As of 3 November:

- **Monitoring.** Each environment has its log group `/cicnids/<env>`, kept for 14 days, and nothing else: no metric filters, alarms or dashboards. The platform stack has the alerts topic `cicnids-alerts`, the budget alerts at USD 50, 100 and 150 publishing to it, and Container Insights on `cicnids-prod` only. Its optional `AlertEmail` subscription is unset: `infra.yml` reads it from the repository variable `ALERT_EMAIL`, which does not exist. The platform stack exports the load balancer's ARN but not its full name, which load balancer metrics use as a dimension.
- **Logs.** They already carry what the metrics need. `page_render` has `page` and `duration_ms`. `ingestion_run` has `status`, `rows_read`, `rows_loaded`, `rows_rejected` and `duration_s`. Each one-off command ends with one line whose event is the command's name (`ingest`, `reconcile`, `migrate` and so on) and whose status is `ok` or `failed` (`pipeline/cli.py`). A failed `ingest` logs that line even when it fails before recording a run, for example on a missing key.
- **Deployments.** `scripts/ci/deploy_env.sh` updates the stack with the job image, starts a service that was stopped by hand, runs `db-bootstrap` and `migrate`, updates the stack with the app image, runs the smoke test and starts `reconcile` without waiting. Test does the same as the other environments, so there are no end-to-end tests. When the RDS instance is stopped, `db-bootstrap` fails, as it did on 2 November.
- **Roles.** The deploy roles in `infra/bootstrap.yaml` have no RDS permissions.
- **Image.** It holds `app/`, `pipeline/`, `contracts/` and `migrations/`; `.dockerignore` leaves out `tests/`.
- **Samples.** The contract tests expect each file in `tests/contracts/<contract>/` to load and each file in `tests/contracts/broken/` to be quarantined for the reason `expected.yaml` gives. The files have 200 to 500 rows each, about 380 kB in all.
- **Upload.** Every app task already receives `UPLOAD_PASSWORD` from its environment's secret, and its task role may put objects anywhere in its bucket.
- **AWS.** Switched off since the evening of 2 November: the four services at 0 tasks, both RDS instances stopped.
- **Timings.** In the last CD runs, the build took about 1 minute and each environment 7 to 8 minutes. Merge to staging took about 25 minutes, and production about 9 minutes after approval.

## 4. The parts

### 4.1 A deployment starts a stopped database

- `scripts/ci/lib.sh` gains a function, for example `ensure_database ENV`. The instance is `cicnids-prod` for production and `cicnids-nonprod` for the other three. It waits while the instance is stopping, starts it when it is stopped, and returns once it is available; in any other state (starting, backing up, modifying) it waits. It gives up after 20 minutes, and it logs what it found and what it did.
- `deploy_env.sh` calls it first, before anything else, so rollbacks benefit too. `ingest.sh` calls it before running the job. The service then starts as it does today.
- In `bootstrap.yaml`, each deploy role may call `rds:DescribeDBInstances`, and `rds:StartDBInstance` on its own tier's instance only. No role may stop an instance. The bootstrap stack is deployed from the laptop (runbook, "First-time setup", step 1) before this pull request merges. The builder runs that deployment only with Hoàng's go-ahead, because it changes IAM.
- The proof: merge this pull request while AWS is still off. CD should start `cicnids-nonprod` in the development job and deploy development, test and staging. After Hoàng approves, it should start `cicnids-prod` and deploy production. The runbook's "Stop and start environments by hand" section then says that starting needs nothing by hand.
- The first deployment after a stop is slower, because starting an RDS instance takes about 5 to 10 minutes. The lead-time targets apply to deployments that find the database running. A deployment that starts an instance leaves it running; stopping it again stays Hoàng's call.

### 4.2 Monitoring and the alarm email

**Metrics.** Metric filters on each environment's log group publish to the namespace `CICNIDS`, with the dimension `Environment` taken from the log line's `env`:

| Metric | Log lines | Value |
| --- | --- | --- |
| PageRenderTime (milliseconds) | event `page_render` | `duration_ms` |
| IngestionDuration (seconds) | event `ingestion_run` | `duration_s` |
| RejectedRows (count) | event `ingestion_run` | `rows_rejected` |
| FailedIngestions (count) | event `ingest` or `reconcile` with status `failed` | 1 |

FailedIngestions counts the command's closing line, not `ingestion_run`. That way, each failure counts once, whether or not it got as far as recording a run.

**Alarms.** Each environment gets five, named `cicnids-<env>-<what>`. Each sends to the alerts topic both when it goes into alarm and when it recovers:

| Alarm | Metric | Fires when |
| --- | --- | --- |
| 5xx | `HTTPCode_Target_5XX_Count` of its target group | the app itself keeps returning 5xx responses |
| CPU | `CPUUtilization` of its ECS service | above 80% for several minutes |
| Memory | `MemoryUtilization` of its ECS service | above 85% for several minutes |
| Unhealthy targets | `UnHealthyHostCount` of its target group | at least one, for several minutes |
| Failed ingestion | `CICNIDS` `FailedIngestions` | any, in a 5-minute period |

Every alarm treats missing data as not breaching, so a stopped environment never alarms. The 5xx alarm counts only responses from the app. When a service is stopped, the load balancer itself answers the bots that probe its ports with 503s; those show on the dashboard but raise no alarm. A crashing app shows up as unhealthy targets. Before choosing periods, the builder reads the last two weeks of CPU and memory for each service. If a service already runs close to a threshold, the pull request says so; it does not ship an alarm that is always on. Alarms in development, test and staging email too, and the environment's name in the alarm's name says where the fault is.

**Dashboards.** Each environment has one, `cicnids-<env>`, built in the environment template. Production's is the demo dashboard and holds everything brief section 4.1 lists:

- requests (`RequestCount`) and latency (`TargetResponseTime`, p50 and p95)
- errors: 5xx from the targets and from the load balancer
- CPU and memory of the service
- network in and out (Container Insights, production only)
- healthy and unhealthy targets
- the four `CICNIDS` metrics
- the state of each alarm

The other environments get the same layout without the network row.

**Email.** The address moves from a repository variable to a repository secret, `ALERT_EMAIL`, so GitHub masks it in logs, and `platform.yaml` marks `AlertEmail` as `NoEcho`, so CloudFormation hides it too. The builder sets the secret with `gh secret set ALERT_EMAIL`, using the address Hoàng gave on 3 November, before pull request 2 merges, because the merge starts the Infrastructure workflow. That workflow updates `cicnids-platform` after Hoàng approves `platform`. AWS emails a confirmation link, which Hoàng opens once. The budget alerts use the same topic, so they reach the same inbox.

**Forced failure.** This meets OPS-06's acceptance test and gives the brief's "one alarm firing". Run the Ingest workflow with a key that does not exist, for example `raw/alarm-test.csv`. The job fails on the missing file and records no run, so nothing appears on the Pipeline page. FailedIngestions counts one, and the alarm emails within 5 minutes, followed by a recovery email. In production the run waits for Hoàng's approval, like every production Ingest run. The runbook gets a "Test the alarms" section.

### 4.3 End-to-end tests in test

A new one-off command, `python -m pipeline e2e`, refuses to run unless `APP_ENV` is `test`. It does this:

1. **Reset.** Delete every row from the data tables of the test database, `cicnids_test`; the schema stays at the latest migration, and the other databases on the non-production instance are never touched. Delete every object under `raw/`, `processed/` and `quarantine/` in the test bucket.
2. **Upload** every contract-test sample. The files of `tests/contracts/<contract>/` go to `raw/<contract>/<file>`. The files of `tests/contracts/broken/` go to `raw/<file>`, so each broken file is its own dataset, like a one-off upload. The upload is what starts the real path: S3, EventBridge, the job task.
3. **Wait** until each uploaded key has a finished run (loaded, quarantined or failed) that started after its upload, for up to 10 minutes.
4. **Check.** Each contract sample loaded, with rows loaded, and its dataset's `has_label` matches its contract. Each broken file was quarantined, its report names the missing fields that `expected.yaml` lists, and its draft contract sits beside the report. No run failed.
5. **Render** every page with AppTest against the test database, once for each loaded dataset: no exception, and no card that failed to load its data.
6. **Report.** Log one `e2e` line per check, and exit with code 1 if any check failed.

Around the command:

- The image adds the end-to-end code and `tests/contracts/`.
- In test, `deploy_env.sh` runs the command after the smoke test and waits for it, instead of starting `reconcile`; after the reset, reconcile would have nothing to do. A failure fails the test job, so staging and production never start. Rollbacks skip the command, because an older image may not have it.
- The test environment's task role may delete objects anywhere in its own bucket; the other environments keep "under `processed/` only". A condition in `environment.yaml` grants this to test alone, and a template test pins it.
- The command takes at most 5 minutes, so merge to staging stays under 30 minutes (section 5).
- The samples drive the test, so the demo's contract pull request extends the end-to-end test by itself. That pull request moves the simulated sample from `broken/` into `tests/contracts/simulated-real-traffic/`. The run after the merge then expects that file to load, and it renders every page for an unlabelled dataset.

### 4.4 Load test during deployments

- `tests/load/locustfile.py` defines one user that loads the page shell (`/`), the static files the shell references, and `/_stcore/health`, waiting 1 to 5 seconds between requests. The test runs 20 users.
- A script, for example `scripts/ci/load_test.sh`, runs Locust headless on the GitHub runner against the environment's URL and keeps its statistics.
- In staging and production only, `deploy_env.sh` starts the load test in the background just before the app update and stops it after the smoke test passes. In production it keeps running until it has run for at least 5 minutes, so every production release produces the brief's performance evidence (20 users for 5 minutes). In staging it stops as soon as the smoke test passes, to protect the lead time.
- **The check.** Any 5xx or failed request fails the deployment (NFR-02). In production the new version is already serving when the check fails; the red job is the signal to look and, if needed, roll back. The 95th percentile and the request counts go to the job summary, and the statistics are kept as a workflow artifact. A 95th percentile above 2 seconds shows as a warning, not a failure: the network between GitHub and AWS varies, and a slow minute is not a fault in the release.
- Locust installs on the runner from its own pinned requirements file. It never enters the image.
- Rollbacks of staging and production run the load test too, because they share `deploy_env.sh`. The rollback drill and the demo's rollback therefore show load on the dashboard and prove that a rollback causes no 5xx.

### 4.5 Rollback drill

After the load-test pull request reaches production, run Rollback with `production` and the previous release's tag; Hoàng approves. Time it from the approval to the passing smoke test: the target is under 10 minutes (OPS-05). Locust runs throughout and must see no 5xx. Then roll forward to the current tag the same way. Record both timings in the runbook's "Roll back" section. That is a docs-only change, so CD skips it.

### 4.6 Upload card (ING-10, Could)

- **Where.** A card on the Pipeline page with a password field, a CSV picker and an Upload button.
- **Upload.** With the right password, compared in constant time against `UPLOAD_PASSWORD`, the file goes to `raw/<file name>`, at the top of `raw/`. It is then its own dataset, like the simulated file. A file of the same name replaces the earlier one, as `aws s3 cp` would. The card cannot reach anything under a dataset folder such as `raw/cse-cic-ids2018/`.
- **After.** The card says that the run starts within a minute or two and will appear under Recent ingestion runs. EventBridge does the rest; the app starts nothing itself.
- **Refusals.** A wrong password uploads nothing and logs an `upload_refused` line, never the password. Without a bucket, on a laptop, the card says that uploads need an environment.
- **Size.** The limit is 100 MB (`server.maxUploadSize`). That covers the 100,000-row simulated file (about 32 MB) within the app task's 1 GB.
- **Password.** The runbook says how to read it: `aws secretsmanager get-secret-value` for the environment's upload-password secret.
- In the demo, the simulated file goes up through this card if it is built; otherwise with `aws s3 cp`, as today.

### 4.7 Demo rehearsal

Run scenario 4.2 in this order and time each step:

1. Production shows the baseline. Open each page once beforehand (runbook).
2. Upload the simulated file to production and to development. Development has held it as loaded since the milestone 2 rehearsal; main's image has no contract for it, so the new upload is quarantined there as well. Its draft contract can be downloaded from the Pipeline page.
3. Make the contract change on a branch (runbook, "Demo", steps 1 and 2), open the pull request, watch CI's contract tests pass, then close it unmerged.
4. In development, run CD by hand on that branch (it deploys development only). Reconcile loads the file again, and the pages hide the label charts for it. Then put development back on main's tag with the Rollback workflow.
5. Push a deliberately broken build: a pull request with a failing test. CI blocks the merge, so the build never reaches development, let alone staging, and production keeps running. Close it.
6. Roll production back to the previous tag and then forward again; Hoàng approves both. Locust runs during each, and the production dashboard shows the load.
7. Force the alarm (section 4.2) during step 6, so the dashboard shows the load and the alarm together, the Level 2 evidence. Wait for the email.

Write the result into the runbook's "Demo" section as a script: what to click, what to show, the expected timings, and where it can stall. Anything that broke gets fixed in its own small pull request.

## 5. Time and cost

**Lead time.** Merge to staging takes about 25 minutes today: the build 1, development 8, test 7, staging 8. This design adds the end-to-end test to test, and Locust's start-up to staging. To stay under 30 minutes:

- the end-to-end command takes at most 5 minutes;
- in staging, Locust runs only while the app switches over;
- Locust installs while the stack update runs.

Production gains a minute or two from the 5-minute load test and stays well within 15 minutes of approval. If the end-to-end test cannot fit, the builder says so in the pull request; the target is not relaxed silently.

**Cost.** These estimates use list prices as remembered in October 2026; Cost Explorer is the check.

- CloudWatch: 16 custom metrics (4 per environment, charged only while they receive data), 20 alarms and 4 dashboards (3 are free) come to under USD 10 a month.
- Locust runs on GitHub's runners and adds no AWS compute. The load balancer capacity it uses for a few minutes per release costs cents.
- The end-to-end test runs one 2 vCPU, 8 GB task for about 5 minutes per release, plus a few short ingestion tasks: cents.
- Starting RDS automatically costs nothing by itself, but an instance a deployment starts keeps running until it is stopped again.

## 6. Shipping

### 6.1 Pull requests

| Pull request | Content |
| --- | --- |
| 1. Database start | The function in `lib.sh`, called by `deploy_env.sh` and `ingest.sh`; the RDS permissions in `bootstrap.yaml`, deployed from the laptop first; the runbook. It merges while AWS is still off, as its own proof. |
| 2. Monitoring and email | Metric filters, alarms and the dashboard in `environment.yaml`; `NoEcho` in `platform.yaml`; `infra.yml` reading the secret; the runbook's "Test the alarms". The Infrastructure workflow updates the platform stack after Hoàng approves `platform`. |
| 3. End-to-end tests | The `e2e` command and its checks; the image's contents; the test-only delete permission; `deploy_env.sh` in test; tests. |
| 4. Load test | The locustfile, the load-test script, `deploy_env.sh` in staging and production, and `deploy.yml` (Locust's requirements and the artifact). |
| 5. Upload card, if time allows | The card on the Pipeline page, the upload in `app/data/storage.py`, the upload limit in `config.toml`, tests. |

The rollback drill and the rehearsal change only `docs/runbook.md`, so their pull requests skip CD.

Each pull request goes the same way:

1. A branch `feat/m4-<part>` and the pull request template. The template's checklist is written for milestone 3's pages, so the first pull request rewords it for any change.
2. Green CI, then merge. Before the first merge, the builder asks Hoàng whether it may merge on green CI as it did in milestone 3.
3. CD takes the change through development, test and staging. The builder checks each environment, then asks Hoàng to approve production with the run's link, and waits.

The next pull request's CD starts only after the previous one reached production. Before any AWS work, Hoàng renews the AWS sign-in (`aws login --profile hoang`) in the browser.

### 6.2 Tests

- **Scripts.** The fake `aws` in `tests/unit/test_ci_scripts.py` covers the database start in each RDS state, and the load test's verdict on recorded Locust statistics, with and without a 5xx.
- **Templates.** `tests/unit/test_environment_template.py` pins that:
  - every alarm sends to the topic and treats missing data as not breaching;
  - the metric filters name events the code logs (`page_render`, `ingestion_run`, and command names from `pipeline.cli.COMMANDS`);
  - only test may delete objects outside `processed/`;
  - each deploy role may start only its own tier's instance;
  - `AlertEmail` is `NoEcho`.
- **End-to-end checks.** Unit tests with fakes, including that the command refuses to run outside test.
- **Upload card.** AppTest for a wrong password, for no bucket, and for an upload to a fake bucket.
- **Linters.** CI's lint job already runs shellcheck and actionlint.

### 6.3 Done when

- **PR 1:** a CD run that started with both instances stopped reaches production, with no manual step other than the approval.
- **PR 2:**
  - the production dashboard shows every widget of section 4.2 with live data;
  - the forced failure's email arrives within 5 minutes;
  - a routine deployment raises no alarm;
  - a night with the environments stopped sends no email.
- **PR 3:** the test job runs the end-to-end test in its own CD run, and it passes.
- **PR 4:** staging and production deployments report Locust results with no 5xx. Production's run covers at least 5 minutes with 20 users, and the job summary shows its 95th percentile.
- **Rollback drill:** production is restored in under 10 minutes, with no 5xx under load.
- **Lead time:** merge to staging stays under 30 minutes, and production finishes within 15 minutes of approval.
- **Rehearsal:** every step of section 4.7 has run, and the runbook's demo script is written.
- **README:** the status line names milestone 4.

## 7. Left to the builder

- Alarm periods, datapoints and the exact 5xx threshold, within section 4.2's rule: a real, lasting fault, never a stopped environment.
- The dashboard's layout and widget types.
- Where the end-to-end code lives (`pipeline/`, where the 80% coverage gate counts it, or `tests/e2e/`, which build design section 9 names) and how it drives AppTest.
- Locust's task mix and the static files it fetches.
- Names of functions and scripts; the ones above are suggestions.
- Wording of log lines, card text and job summaries.
- Splitting a part into more than one pull request if it grows.
