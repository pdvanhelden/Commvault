# Azure Managed-Disk Snapshot TCO Assessment

## Purpose

`azure_snapshot_tco_assessment_updated.py` is a read-only assessment script for identifying native Azure managed-disk snapshots that may represent a TCO optimisation opportunity.

The script:

- Inventories managed-disk snapshots across one or more Azure subscriptions.
- Checks whether the source managed disk still exists.
- Reports logical snapshot size, age, location, SKU, tags, and incremental status.
- Classifies each snapshot for review.
- Calculates directional monthly and annual storage exposure using a supplied rate and utilisation assumption.
- Produces a detailed CSV report and a JSON summary.

The script does not delete resources.

## Important interpretation

Azure snapshot billing is based on used storage. The Azure management-plane snapshot property exposed to this script provides the logical disk size, not the exact billed snapshot usage. Cost values produced by this script are therefore directional storage-exposure estimates, not Azure invoice values or guaranteed savings.

A snapshot whose source disk no longer exists is not automatically unnecessary. It may be retained intentionally for recovery, compliance, legal hold, migration, or another operational reason. Review ownership and retention requirements before taking any action.

## Requirements

- Python 3.10 or later
- Azure CLI, Azure Cloud Shell, managed identity, workload identity, or another credential supported by `DefaultAzureCredential`
- Read access to the target subscription and its managed disks and snapshots
- The script file: `azure_snapshot_tco_assessment_updated.py`

### Python packages

```bash
python3 -m pip install --user \
  azure-identity \
  azure-mgmt-compute \
  azure-mgmt-subscription
```

If you use a virtual environment:

```bash
python3 -m venv snapshot-assessment
source snapshot-assessment/bin/activate
python -m pip install \
  azure-identity \
  azure-mgmt-compute \
  azure-mgmt-subscription
```

`azure-mgmt-subscription` is optional when `--subscription` is always supplied, but installing it enables automatic discovery of enabled subscriptions.

## Authentication

### Azure Cloud Shell

Azure Cloud Shell is normally already authenticated. Verify the active context:

```bash
az account show --output table
```

### Local shell

```bash
az login
az account list --output table
az account set --subscription "<subscription-id>"
```

The Python script uses `DefaultAzureCredential`. An Azure CLI login is one supported authentication route.

## Quick start

Run against one subscription:

```bash
python3 azure_snapshot_tco_assessment_updated.py \
  --subscription <subscription-id> \
  --min-age-days 90 \
  --high-confidence-age-days 180 \
  --utilization-percent 50 \
  --default-rate 0.05
```

This writes:

- `azure_snapshot_tco.csv`
- `azure_snapshot_tco_summary.json`

## Recommended assessment examples

### One subscription, upper-bound logical-size model

```bash
python3 azure_snapshot_tco_assessment_updated.py \
  --subscription <subscription-id> \
  --min-age-days 90 \
  --high-confidence-age-days 180 \
  --utilization-percent 100 \
  --default-rate 0.05 \
  --currency USD
```

### Multiple subscriptions

Repeat `--subscription`:

```bash
python3 azure_snapshot_tco_assessment_updated.py \
  --subscription <subscription-id-1> \
  --subscription <subscription-id-2> \
  --min-age-days 90 \
  --high-confidence-age-days 180 \
  --utilization-percent 50 \
  --default-rate 0.05
```

### Use regional rates

Create `azure_snapshot_rates.json`:

```json
{
  "westeurope": 0.05,
  "northeurope": 0.05,
  "eastus2": 0.05,
  "francecentral": 0.05,
  "default": 0.05
}
```

Run:

```bash
python3 azure_snapshot_tco_assessment_updated.py \
  --subscription <subscription-id> \
  --rates-json azure_snapshot_rates.json \
  --utilization-percent 50
```

Use the customer's actual contracted rates where available. Do not assume the example rates represent current Azure pricing.

### Apply tag guardrails

Never treat snapshots tagged `LegalHold=true` or `Retain=true` as TCO opportunities:

```bash
python3 azure_snapshot_tco_assessment_updated.py \
  --subscription <subscription-id> \
  --protect-tag LegalHold=true \
  --protect-tag Retain=true \
  --min-age-days 90 \
  --high-confidence-age-days 180 \
  --utilization-percent 50 \
  --default-rate 0.05
```

Only consider snapshots matching a specified tag:

```bash
python3 azure_snapshot_tco_assessment_updated.py \
  --subscription <subscription-id> \
  --include-tag ManagedBy=NativeBackup \
  --min-age-days 90 \
  --high-confidence-age-days 180 \
  --utilization-percent 50 \
  --default-rate 0.05
```

## Classification logic

- **Active**: The referenced source managed disk exists.
- **Recovery Candidate**: A protection tag matches, a required inclusion tag is missing, or the snapshot is younger than the minimum-age threshold.
- **Review Required**: The source is absent, unparseable, not a managed-disk resource ID, or could not be validated.
- **TCO Opportunity**: The source disk is missing and the minimum-age threshold is met.
- **High TCO Opportunity**: The source disk is missing, the high-confidence age threshold is met, and the snapshot has no tags.

These labels prioritise customer review. They do not mean a snapshot is safe to delete.

## Main command-line options

- `--subscription`: Subscription ID. Repeatable.
- `--tenant-id`: Optional tenant ID.
- `--min-age-days`: Minimum age before a missing-source snapshot becomes a TCO opportunity. Default: 90.
- `--high-confidence-age-days`: Age threshold for High TCO Opportunity. Default: 180.
- `--include-tag KEY=VALUE`: Only allow matching snapshots into opportunity classifications. Repeatable.
- `--protect-tag KEY=VALUE`: Keep matching snapshots out of opportunity classifications. Repeatable.
- `--include-no-source`: Allows old snapshots without a source-resource ID to become candidates. This is less conservative and should be used cautiously.
- `--rates-json`: Regional rate file.
- `--default-rate`: Fallback per-GiB-month rate.
- `--currency`: Report currency label. Default: USD.
- `--utilization-percent`: Assumed billable percentage of logical size. Default: 100.
- `--output`: CSV output path.
- `--summary-output`: JSON summary output path.
- `--log-level`: Logging level.

View the script's current options:

```bash
python3 azure_snapshot_tco_assessment_updated.py --help
```

## Output interpretation

### CSV

The detailed CSV contains one row per snapshot, including:

- Subscription, resource group, location, and snapshot identity
- Source disk identity and existence check
- Age, logical size, snapshot type, and SKU
- Supplied rate and utilisation assumption
- Directional monthly and annual storage exposure
- Classification, rationale, and tags

### JSON summary

The summary contains:

- Inventory count
- Opportunity count
- Opportunity logical size
- Estimated billable GiB under the selected assumption
- Monthly and annual directional storage exposure
- Classification counts
- Scan errors

## Quick functional test

Use only a disposable test subscription or resource group.

```bash
az disk create \
  --resource-group <test-resource-group> \
  --name tco-test-disk \
  --size-gb 32 \
  --sku Standard_LRS

az snapshot create \
  --resource-group <test-resource-group> \
  --name tco-test-snapshot \
  --source tco-test-disk
```

Run with zero minimum age. The test snapshot should initially be classified as Active:

```bash
python3 azure_snapshot_tco_assessment_updated.py \
  --subscription <subscription-id> \
  --min-age-days 0 \
  --high-confidence-age-days 999 \
  --default-rate 0.05
```

Delete only the disposable source disk:

```bash
az disk delete \
  --resource-group <test-resource-group> \
  --name tco-test-disk \
  --yes
```

Run the assessment again. The test snapshot should become a TCO Opportunity.

Clean up after validation:

```bash
az snapshot delete \
  --resource-group <test-resource-group> \
  --name tco-test-snapshot
```

## Suggested TCO presentation approach

Run three scenarios against the same inventory:

- 25% utilisation: lower directional estimate
- 50% utilisation: middle directional estimate
- 100% utilisation: logical-size upper-bound model

Present the result as a range of potential storage exposure. Do not present it as confirmed savings until the customer validates actual used capacity, retention intent, ownership, legal-hold requirements, and Azure billing data.

## Troubleshooting

### `SubscriptionClient` cannot be imported

Install:

```bash
python3 -m pip install --user azure-mgmt-subscription
```

Alternatively, always pass `--subscription`. The script provides a clear error if automatic subscription discovery is requested but the subscription package is unavailable.

### Permission denied while installing packages in Cloud Shell

Use `--user` or a virtual environment:

```bash
python3 -m pip install --user azure-identity azure-mgmt-compute azure-mgmt-subscription
```

### Authentication errors

Check:

```bash
az account show
```

Confirm that the identity can list snapshots and read source managed disks in every assessed subscription.

### Empty cost fields

Supply either `--default-rate` or `--rates-json`.

### Scan errors in the summary

Review `scan_errors` in the JSON summary. A partial report should not be treated as a complete subscription assessment.

## Security and customer-sharing guidance

- Use a read-only identity and least-privilege access.
- Do not embed secrets, tokens, or passwords in the script.
- Review CSV tags and descriptions for customer-sensitive information before sharing report output.
- Keep the original inventory and all assumptions with the TCO analysis.
- Obtain customer approval before deleting any snapshot. This script does not perform deletion.
