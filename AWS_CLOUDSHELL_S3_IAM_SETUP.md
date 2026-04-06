# AWS CloudShell: S3 IAM Permissions for Lambda Snapshot Access

This guide configures the Lambda execution role so it can:

- List bucket keys under a prefix: s3:ListBucket
- Read snapshot objects: s3:GetObject
- Write snapshot objects: s3:PutObject

It also includes verification, troubleshooting, and rollback commands.

## 1) Set variables

~~~bash
ROLE_NAME="telegram-fuel-bot-function-role-8kvdyzes"
BUCKET="telegram-bot-s3-snapshots"
PREFIX="prices/*"
POLICY_NAME="FuelSnapshotsS3Access"
~~~

If your role or bucket names differ, change them before running the next steps.

## 2) Create inline IAM policy JSON

~~~bash
cat > /tmp/fuel-snapshots-s3-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "FuelSnapshotsBucketList",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::${BUCKET}",
      "Condition": {
        "StringLike": {
          "s3:prefix": [
            "${PREFIX}"
          ]
        }
      }
    },
    {
      "Sid": "FuelSnapshotsObjectsRW",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject"
      ],
      "Resource": "arn:aws:s3:::${BUCKET}/${PREFIX}"
    }
  ]
}
EOF
~~~

## 3) Attach policy to the Lambda role

~~~bash
aws iam put-role-policy \
  --role-name "${ROLE_NAME}" \
  --policy-name "${POLICY_NAME}" \
  --policy-document file:///tmp/fuel-snapshots-s3-policy.json
~~~

## 4) Verify policy is attached

~~~bash
aws iam get-role-policy \
  --role-name "${ROLE_NAME}" \
  --policy-name "${POLICY_NAME}"
~~~

## 5) Validate S3 access behavior

Check whether snapshot objects are present and readable.

~~~bash
aws s3api list-objects-v2 \
  --bucket "${BUCKET}" \
  --prefix "prices/" \
  --max-items 20
~~~

~~~bash
aws s3api head-object \
  --bucket "${BUCKET}" \
  --key "prices/previous.json"
~~~

Expected outcomes:

- list-objects-v2 succeeds: ListBucket permission is active.
- head-object returns 200: previous.json exists.
- head-object returns 404: previous.json does not exist yet (normal before first rotation).

## 6) Trigger first snapshot creation

If your EventBridge schedule has not run yet, invoke the Lambda manually once:

~~~bash
aws lambda invoke \
  --function-name telegram-fuel-bot-function \
  --cli-binary-format raw-in-base64-out \
  --payload '{"source":"aws.events"}' \
  /tmp/snapshot-run-response.json
~~~

Check function response payload:

~~~bash
cat /tmp/snapshot-run-response.json
~~~

Then check current snapshot:

~~~bash
aws s3api head-object \
  --bucket "${BUCKET}" \
  --key "prices/current.json"
~~~

Optional: show only last modified timestamp:

~~~bash
aws s3api head-object \
  --bucket "${BUCKET}" \
  --key "prices/current.json" \
  --query 'LastModified' \
  --output text
~~~

Note:

- previous.json is created after a price change rotation, not always on first write.

## 7) Rollback: remove the inline policy

~~~bash
aws iam delete-role-policy \
  --role-name "${ROLE_NAME}" \
  --policy-name "${POLICY_NAME}"
~~~

## 8) One-liner version (attach + verify)

~~~bash
ROLE_NAME="telegram-fuel-bot-function-role-8kvdyzes"; BUCKET="telegram-bot-s3-snapshots"; PREFIX="prices/*"; POLICY_NAME="FuelSnapshotsS3Access"; cat > /tmp/fuel-snapshots-s3-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "FuelSnapshotsBucketList",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::${BUCKET}",
      "Condition": { "StringLike": { "s3:prefix": ["${PREFIX}"] } }
    },
    {
      "Sid": "FuelSnapshotsObjectsRW",
      "Effect": "Allow",
      "Action": ["s3:GetObject","s3:PutObject"],
      "Resource": "arn:aws:s3:::${BUCKET}/${PREFIX}"
    }
  ]
}
EOF
aws iam put-role-policy --role-name "${ROLE_NAME}" --policy-name "${POLICY_NAME}" --policy-document file:///tmp/fuel-snapshots-s3-policy.json; aws iam get-role-policy --role-name "${ROLE_NAME}" --policy-name "${POLICY_NAME}"
~~~
