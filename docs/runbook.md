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
3. For each environment, `scripts/ci/deploy_env.sh` updates the stack with the new job image, runs `db-bootstrap` and the migrations as one-off ECS tasks, updates the stack with the new app image, and runs the smoke test.
4. Development, test and staging deploy in turn. Production waits in the CD run until a reviewer opens it, chooses **Review deployments** and approves `production`. The production job then writes a parity table: the tag each environment runs.

Changes to `docs/` or Markdown files do not start CD. Changes to the shared templates start the Infrastructure workflow, which waits for approval in `platform`.

## Roll back

Run the **Rollback** workflow with the environment and the earlier tag. It redeploys that image without migrations; migrations only add before they remove, so an older image keeps working against the newer schema. The run summary lists the newest ten tags. Production still needs approval.

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
- An AWS free account plan rejects RDS backups longer than one day and allows two RDS instances at a time, counting instances that are still being deleted. The project account is on the paid plan, but the templates keep one-day backups.
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
