# AWS EBS Snapshot TCO Assessment

## Purpose

`aws_snapshot_tco_assessment.py` is a read-only assessment script for identifying native Amazon EBS snapshots that may represent a TCO optimisation opportunity.

The script:

- Inventories account-owned EBS snapshots across enabled AWS Regions.
- Checks whether the source EBS volume still exists.
- Checks whether a snapshot is referenced by a private AMI.
- Reports logical snapshot size, age, storage tier, tags, and encryption state.
- Classifies snapshots for review.
- Calculates directional monthly and annual storage exposure using a supplied rate and utilisation assumption.
- Produces a detailed CSV report and a JSON summary.

The script does not delete snapshots or deregister AMIs.

## Important interpretation

EBS snapshots are incremental. AWS charges for stored snapshot blocks, not the logical size of the source volume. Deleting a snapshot may not remove blocks that are still referenced by another snapshot. The report's cost values are therefore directional storage-exposure estimates, not Cost Explorer values, CUR values, invoice values, or guaranteed savings.

A snapshot whose source volume no longer exists is not automatically unnecessary. It may be intentionally retained for disaster recovery, compliance, legal hold, migration, AMI use, or another operational reason. The script excludes private-AMI-referenced snapshots from candidate classifications, but business ownership and retention intent must still be reviewed.

## Requirements

- Python 3.10 or later
- AWS credentials provided through the standard AWS SDK credential chain
- Read access to EC2 volumes, snapshots, regions, and private AMIs
- STS access to identify the caller
- Optional STS AssumeRole access for multi-account assessments
- The script file: `aws_snapshot_tco_assessment.py`

### Python package

```bash
python3 -m pip install --user boto3
```

Using a virtual environment:

```bash
python3 -m venv snapshot-assessment
source snapshot-assessment/bin/activate
python -m pip install boto3
```

## Authentication

The script uses the normal boto3 credential chain. Common methods include:

- An AWS CLI profile
- Environment-based credentials
- An EC2 or container role
- An assumed role specified to the script

Verify access:

```bash
aws sts get-caller-identity --profile <profile-name>
```

List configured profiles:

```bash
aws configure list-profiles
```

Do not embed access keys or secret keys in the script.

## Quick start

Run against one profile and all enabled Regions:

```bash
python3 aws_snapshot_tco_assessment.py \
  --profile <profile-name> \
  --min-age-days 90 \
  --high-confidence-age-days 180 \
  --utilization-percent 50 \
  --default-rate 0.05
```

This writes:

- `aws_snapshot_tco.csv`
- `aws_snapshot_tco_summary.json`

## Recommended assessment examples

### Limit the scan to selected Regions

```bash
python3 aws_snapshot_tco_assessment.py \
  --profile <profile-name> \
  --regions eu-west-1 eu-central-1 \
  --min-age-days 90 \
  --high-confidence-age-days 180 \
  --utilization-percent 50 \
  --default-rate 0.05
```

### Multiple AWS CLI profiles

Repeat `--profile`:

```bash
python3 aws_snapshot_tco_assessment.py \
  --profile sandbox \
  --profile production-readonly \
  --min-age-days 90 \
  --high-confidence-age-days 180 \
  --utilization-percent 50 \
  --default-rate 0.05
```

### Assume roles in multiple accounts

```bash
python3 aws_snapshot_tco_assessment.py \
  --profile management \
  --role-arn arn:aws:iam::<account-id-1>:role/SnapshotAssessmentReadOnly \
  --role-arn arn:aws:iam::<account-id-2>:role/SnapshotAssessmentReadOnly \
  --min-age-days 90 \
  --high-confidence-age-days 180 \
  --utilization-percent 50 \
  --default-rate 0.05
```

If the role trust requires an external ID:

```bash
python3 aws_snapshot_tco_assessment.py \
  --profile management \
  --role-arn arn:aws:iam::<account-id>:role/SnapshotAssessmentReadOnly \
  --external-id <external-id> \
  --default-rate 0.05
```

### Use regional rates

Create `aws_snapshot_rates.json`:

```json
{
  "eu-west-1": 0.05,
  "eu-central-1": 0.05,
  "us-east-1": 0.05,
  "default": 0.05
}
```

Run:

```bash
python3 aws_snapshot_tco_assessment.py \
  --profile <profile-name> \
  --rates-json aws_snapshot_rates.json \
  --utilization-percent 50
```

Use the customer's contracted rates where available. Do not assume the example rates represent current AWS pricing.

### Apply tag guardrails

Protect legal-hold and retained snapshots:

```bash
python3 aws_snapshot_tco_assessment.py \
  --profile <profile-name> \
  --protect-tag LegalHold=true \
  --protect-tag Retain=true \
  --min-age-days 90 \
  --high-confidence-age-days 180 \
  --utilization-percent 50 \
  --default-rate 0.05
```

Only consider snapshots matching a specified tag:

```bash
python3 aws_snapshot_tco_assessment.py \
  --profile <profile-name> \
  --include-tag ManagedBy=NativeBackup \
  --min-age-days 90 \
  --high-confidence-age-days 180 \
  --utilization-percent 50 \
  --default-rate 0.05
```

## Classification logic

The current AWS script uses these classifications:

- **Active**: The source EBS volume exists or the snapshot is referenced by a private AMI.
- **Recovery Candidate**: A protection tag matches, a required inclusion tag is missing, or the snapshot is younger than the minimum-age threshold.
- **Potentially Orphaned**: The source volume is missing, no private AMI references the snapshot, and the minimum-age threshold is met.
- **High Confidence Orphan**: The source volume is missing, no private AMI references the snapshot, the high-confidence age threshold is met, and the snapshot has no tags.

These labels are technical screening categories. They do not mean a snapshot is safe to delete. For a customer-facing TCO discussion, consider presenting the last two categories as TCO opportunities rather than deletion recommendations.

## Main command-line options

- `--profile`: AWS CLI profile. Repeatable.
- `--role-arn`: Role ARN to assume. Repeatable.
- `--external-id`: Optional external ID for AssumeRole.
- `--regions`: Regions to scan. Default: all enabled Regions.
- `--min-age-days`: Minimum age before a missing-source snapshot becomes a candidate. Default: 90.
- `--high-confidence-age-days`: Age threshold for the high-confidence classification. Default: 180.
- `--include-tag KEY=VALUE`: Only allow matching snapshots into candidate classifications. Repeatable.
- `--protect-tag KEY=VALUE`: Keep matching snapshots out of candidate classifications. Repeatable.
- `--rates-json`: Regional rate file.
- `--default-rate`: Fallback per-GiB-month rate.
- `--currency`: Report currency label. Default: USD.
- `--utilization-percent`: Assumed billable percentage of logical size. Default: 100.
- `--output`: CSV output path.
- `--summary-output`: JSON summary output path.
- `--log-level`: Logging level.

View the script's current options:

```bash
python3 aws_snapshot_tco_assessment.py --help
```

## Output interpretation

### CSV

The detailed CSV contains one row per snapshot, including:

- Account, Region, snapshot ID, and volume ID
- Source-volume existence check
- Private-AMI reference check
- Age, logical volume size, storage tier, and encryption status
- Supplied rate and utilisation assumption
- Directional monthly and annual cost estimate
- Classification, rationale, description, and tags

### JSON summary

The summary contains:

- Inventory count
- Candidate count
- Candidate logical GiB
- Estimated billable GiB under the selected assumption
- Directional monthly and annual cost
- Classification counts
- Scan errors

## Quick functional test

Use only a disposable AWS sandbox account and Region.

Create a 32 GiB test volume in an Availability Zone in the selected Region:

```bash
aws ec2 create-volume \
  --profile <profile-name> \
  --region eu-west-1 \
  --availability-zone eu-west-1a \
  --volume-type gp3 \
  --size 32 \
  --tag-specifications 'ResourceType=volume,Tags=[{Key=Name,Value=tco-test-volume}]'
```

Capture the returned `VolumeId`, then wait until it is available:

```bash
aws ec2 wait volume-available \
  --profile <profile-name> \
  --region eu-west-1 \
  --volume-ids <volume-id>
```

Create a snapshot:

```bash
aws ec2 create-snapshot \
  --profile <profile-name> \
  --region eu-west-1 \
  --volume-id <volume-id> \
  --description "Snapshot TCO script test" \
  --tag-specifications 'ResourceType=snapshot,Tags=[{Key=Name,Value=tco-test-snapshot}]'
```

Capture the returned `SnapshotId`, then wait until it completes:

```bash
aws ec2 wait snapshot-completed \
  --profile <profile-name> \
  --region eu-west-1 \
  --snapshot-ids <snapshot-id>
```

Run the report. The snapshot should initially be Active:

```bash
python3 aws_snapshot_tco_assessment.py \
  --profile <profile-name> \
  --regions eu-west-1 \
  --min-age-days 0 \
  --high-confidence-age-days 999 \
  --default-rate 0.05
```

Delete only the disposable volume:

```bash
aws ec2 delete-volume \
  --profile <profile-name> \
  --region eu-west-1 \
  --volume-id <volume-id>
```

Run the assessment again. The test snapshot should become Potentially Orphaned.

Clean up after validation:

```bash
aws ec2 delete-snapshot \
  --profile <profile-name> \
  --region eu-west-1 \
  --snapshot-id <snapshot-id>
```

## Suggested TCO presentation approach

Run three scenarios against the same inventory:

- 25% utilisation: lower directional estimate
- 50% utilisation: middle directional estimate
- 100% utilisation: logical-size upper-bound model

Present a range of potential storage exposure. Do not present the result as confirmed savings until the customer validates ownership, recovery intent, snapshot lineage, retention policy, legal-hold requirements, and actual AWS billing data.

## Troubleshooting

### No credentials found

Verify:

```bash
aws sts get-caller-identity --profile <profile-name>
```

### AccessDenied errors

The assessment identity needs read access for Regions, volumes, snapshots, private AMIs, and STS identity. AssumeRole scans also require permission to assume the target role.

### Empty cost fields

Supply either `--default-rate` or `--rates-json`.

### Snapshot remains Active after the source volume is deleted

Check whether the snapshot is referenced by a private AMI. The script intentionally treats private-AMI-referenced snapshots as Active.

### Scan errors in the summary

Review `scan_errors` in the JSON summary. A partial report should not be presented as a complete assessment.

## Security and customer-sharing guidance

- Use read-only IAM roles and least privilege.
- Prefer roles and temporary credentials over long-lived access keys.
- Do not embed credentials in the script or README.
- Review snapshot descriptions and tags for customer-sensitive information before sharing report output.
- Keep the original inventory and all assumptions with the TCO analysis.
- Obtain customer approval before deleting any snapshot. This script does not perform deletion.
