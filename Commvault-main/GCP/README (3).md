# GCP Workload Sizer

## Overview

`GCP Sizer.ps1` inventories supported workloads across one or more Google Cloud projects and exports the results for sizing and analysis.

The script collects information about:

- Google Compute Engine virtual machines
- Attached persistent disks
- Unattached persistent disks
- Cloud SQL instances
- Spanner instances
- BigQuery datasets and tables
- Google Kubernetes Engine clusters
- Google Cloud Storage buckets and objects

For each supported workload, the script captures relevant counts, storage usage, locations, encryption information, configuration details, and labels where available. It creates separate CSV files, an execution log, and a ZIP archive containing the generated results.

## Important limitation in the current script

The current script references the function `Anonymize-Collection`, but that function is not included in the supplied script. Therefore, **do not use the `-Anonymize` switch unless the missing anonymisation function has been added**. Running with `-Anonymize` in its current form will result in an error when the script reaches the anonymisation stage.

The parameters `-AnonymizeFields` and `-NotAnonymizeFields` are declared, but the supplied code does not process them directly.

## Script requirements

The script declares the following requirements:

- PowerShell 7.0 or later
- The PowerShell `GoogleCloud` module
- Google Cloud CLI, because the script calls `gcloud` for Spanner and BigQuery discovery
- An authenticated Google Cloud identity with sufficient read access to the projects and resources being assessed

## Workloads and information collected

### Google Compute Engine

For each VM, the script records:

- Project ID
- Zone
- VM name
- VM status
- Total attached disk count
- Total attached disk size in GB and TB
- Number and total size of disks with a disk encryption key
- VM labels

For each attached or unattached disk, it records:

- Project ID
- Zone
- VM name, for attached disks
- Disk name
- Size in GB and TB
- Disk encryption key information
- Source image
- Disk labels

### Cloud SQL

For each Cloud SQL instance, the script records:

- Project ID
- Instance name
- Region
- Tier
- Storage size in GB
- Storage type
- User labels

### Spanner

For each Spanner instance, the script records:

- Project ID
- Instance ID
- Configuration
- Node count
- Labels

### BigQuery

For each BigQuery dataset, the script lists its tables, queries each table's metadata, and records:

- Project ID
- Dataset ID
- Table count
- Combined table size in GB
- Dataset labels

### Google Kubernetes Engine

For each GKE cluster, the script records:

- Project ID
- Cluster name
- Location
- Kubernetes control-plane version
- Node-pool names
- Total initial node count across node pools
- Resource labels

### Google Cloud Storage

For each GCS bucket, the script lists its objects and records:

- Project ID
- Bucket name
- Location
- Storage class
- Object count
- Combined object size in GB
- Bucket labels

## Permissions

Use a Google Cloud identity with read-only access to every service that must be inventoried. The exact roles required depend on the selected projects and the services enabled there.

At minimum, the identity must be able to:

- List accessible projects
- List and read Compute Engine VMs and disks
- List Cloud SQL instances
- List Spanner instances
- List BigQuery datasets and tables and read table metadata
- List GKE clusters
- List GCS buckets and objects

If the identity cannot access a service, the script reports a warning or error for that service. Some collection can continue, but the resulting inventory may be incomplete.

## Install prerequisites

### 1. Verify PowerShell

Open PowerShell and check the installed version:

```powershell
$PSVersionTable.PSVersion
```

The major version must be 7 or higher.

### 2. Install the GoogleCloud PowerShell module

```powershell
Install-Module GoogleCloud -Scope CurrentUser
```

If prompted to trust the PowerShell Gallery, review the prompt and approve it according to your organisation's policy.

Verify that the module is available:

```powershell
Get-Module GoogleCloud -ListAvailable
```

### 3. Verify Google Cloud CLI

```powershell
gcloud version
```

The `gcloud` executable must be available in the same environment in which the PowerShell script runs.

## Authenticate to Google Cloud

Authenticate the Google Cloud CLI:

```powershell
gcloud auth login
```

The GoogleCloud PowerShell module may also require Application Default Credentials:

```powershell
gcloud auth application-default login
```

Confirm the active CLI identity:

```powershell
gcloud auth list
```

List the projects visible to the authenticated identity:

```powershell
gcloud projects list
```

## Download the script

Download the script from [GCP Sizer.ps1 on GitHub](https://raw.githubusercontent.com/pdvanhelden/Commvault/refs/heads/main/Commvault-main/GCP/GCP%20Sizer.ps1), or use PowerShell:

```powershell
Invoke-WebRequest `
  -Uri "https://raw.githubusercontent.com/pdvanhelden/Commvault/refs/heads/main/Commvault-main/GCP/GCP%20Sizer.ps1" `
  -OutFile "./GCP Sizer.ps1"
```

Change to the download directory before running the script:

```powershell
cd "/path/to/download/directory"
```

Because the filename contains a space, use PowerShell's call operator and quote the path.

## Usage modes

The script has three mutually exclusive project-selection modes.

### Option 1: Scan all accessible projects

```powershell
& "./GCP Sizer.ps1" -GetAllProjects
```

The switch is optional because `GetAllProjects` is the default parameter set. The following command therefore also discovers all accessible projects:

```powershell
& "./GCP Sizer.ps1"
```

Use this mode only when the authenticated identity is intended to assess every project it can access.

### Option 2: Scan selected projects

Provide a comma-separated list of Google Cloud project IDs:

```powershell
& "./GCP Sizer.ps1" -Projects "project-id-1,project-id-2,project-id-3"
```

Use project IDs, not project display names. Avoid spaces around the commas because the script passes each split value directly to `Get-GcpProject` without trimming it.

For an initial validation, run against one non-production project:

```powershell
& "./GCP Sizer.ps1" -Projects "my-test-project-id"
```

### Option 3: Read project IDs from a file

Create a plain-text file containing one project ID per line:

```text
project-id-1
project-id-2
project-id-3
```

Then run:

```powershell
& "./GCP Sizer.ps1" -ProjectFile "./projects.txt"
```

Avoid empty lines and leading or trailing spaces in the project file because the script reads and submits each line directly as a project ID.

## Anonymisation options

The script declares these parameters:

```text
-Anonymize
-AnonymizeFields <string>
-NotAnonymizeFields <string>
```

However, the supplied script does not include the referenced `Anonymize-Collection` function and does not implement handling for the two field-list parameters. **Do not use these options with the current script.**

A normal, non-anonymised run is performed by omitting all three options:

```powershell
& "./GCP Sizer.ps1" -Projects "my-test-project-id"
```

Treat the generated files as potentially sensitive because they can contain project IDs, resource names, labels, locations, capacities, and configuration data.

## Output files

The script creates timestamped files in the current working directory. The timestamp format is:

```text
yyyy-MM-dd_HHmmss
```

A normal run can create:

```text
gce_vm_info-<timestamp>.csv
gce_attached_disk_info-<timestamp>.csv
gce_unattached_disk_info-<timestamp>.csv
gcp_cloudsql_info-<timestamp>.csv
gcp_spanner_info-<timestamp>.csv
gcp_bigquery_info-<timestamp>.csv
gcp_gke_info-<timestamp>.csv
gcp_gcs_info-<timestamp>.csv
output_gcp_<timestamp>.log
gcp_sizing_results_<timestamp>.zip
```

The ZIP contains the result CSVs and the normal output log that exist when compression is performed.

The console summary reports the collected counts for:

- VMs
- Attached disks
- Unattached disks
- Cloud SQL instances
- Spanner instances
- BigQuery datasets
- GKE clusters
- GCS buckets

## Recommended test procedure

1. Use an identity with read-only permissions.
2. Start with one small, non-production GCP project.
3. Verify that PowerShell 7, the GoogleCloud module, and `gcloud` are available.
4. Authenticate with `gcloud auth login` and, if required, `gcloud auth application-default login`.
5. Run:

```powershell
& "./GCP Sizer.ps1" -Projects "my-test-project-id"
```

6. Review the terminal for red or yellow errors.
7. Inspect the timestamped log.
8. Open each CSV and compare a sample of the reported resources with the Google Cloud console.
9. Confirm that `gcp_sizing_results_<timestamp>.zip` contains the expected output.
10. Only then expand the run to additional projects.

## Operational considerations

### Runtime and API activity

The script performs detailed enumeration rather than relying only on high-level totals:

- It retrieves each attached disk separately.
- It describes each BigQuery table separately to calculate dataset size.
- It lists objects in each GCS bucket to calculate bucket size and object count.

Projects with many VMs, disks, tables, buckets, or objects can therefore generate substantial API activity. Run against a limited test scope first and monitor for API errors, permissions issues, and incomplete results.

### Partial results

Several workload sections catch errors and continue. A completed ZIP does not necessarily mean every service was inventoried successfully. Always review the log and console messages for failed projects or services.

For Compute Engine, failure to list VMs causes the script to continue to the next project, so other workload sections in that same project are skipped. This is important when evaluating completeness.

### Storage units

The script reports disk sizes in GB and calculates disk TB values by dividing GB by 1,000. BigQuery and GCS sizes are calculated by dividing bytes by PowerShell's `1GB` constant. Keep this difference in mind when comparing CSV totals.

### Current-project configuration

The script passes project IDs explicitly to the workload commands. Selecting a default project with `gcloud config set project` is therefore not required when using `-Projects` or `-ProjectFile`, although the authenticated identity must still have access to each specified project.

## Troubleshooting

### PowerShell reports that version 7 is required

Start the script with PowerShell 7 using `pwsh`, not Windows PowerShell 5.1.

```powershell
pwsh
& "./GCP Sizer.ps1" -Projects "my-test-project-id"
```

### Required module is missing

If PowerShell reports that `GoogleCloud` is not installed:

```powershell
Install-Module GoogleCloud -Scope CurrentUser
Import-Module GoogleCloud
```

### `gcloud` is not recognised

Install the Google Cloud CLI and start a new terminal session. Verify it with:

```powershell
gcloud version
```

### A project cannot be found

Confirm that the value is a project ID and that the authenticated identity can see it:

```powershell
gcloud projects describe "PROJECT_ID"
```

Also check for spaces in a comma-separated `-Projects` value or in `projects.txt`.

### Permission or API errors

Review the service named in the error. Confirm that:

- The relevant API is enabled in the project.
- The authenticated identity has permission to list and read that resource type.
- The project has not been excluded unintentionally.

Because the script catches several service-specific errors, inspect the complete log even if the script reaches the summary.

### BigQuery or Spanner collection fails

These sections call the external `gcloud` executable. Confirm authentication and test the exact account and project outside the script:

```powershell
gcloud auth list
gcloud config list
```

Then review the error emitted by the corresponding `gcloud` command in the transcript.

### GCS collection is slow

The script enumerates objects in every discovered bucket to calculate object count and total size. Limit the first test to a small project and review the results before running against a larger estate.

### Anonymisation fails

Do not run with `-Anonymize` until `Anonymize-Collection` and the intended field-selection logic have been added to the script.

### Script execution is blocked on Windows

Review the current execution policies:

```powershell
Get-ExecutionPolicy -List
```

If allowed by organisational policy, use a process-scoped setting for the current PowerShell session:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
& "./GCP Sizer.ps1" -Projects "my-test-project-id"
```

Do not make a permanent policy change unless it is approved by your organisation.

## Security and data handling

- Review the script before running it.
- Use least-privilege, read-only access.
- Do not place credentials, access tokens, or service-account keys in the script.
- Store the CSV, log, and ZIP files in an approved location.
- Review labels and resource names for customer-identifying or sensitive information before sharing outputs.
- Securely delete temporary local copies when they are no longer required.
- Record which identity, project scope, script version, and execution command were used.

## Example validation checklist

- [ ] PowerShell 7 or later is in use.
- [ ] The `GoogleCloud` PowerShell module is installed.
- [ ] Google Cloud CLI is available.
- [ ] The correct Google identity is authenticated.
- [ ] The identity has read access to the intended project or projects.
- [ ] A one-project test completed.
- [ ] Red and yellow errors were reviewed.
- [ ] CSV results were spot-checked against the Google Cloud console.
- [ ] The ZIP contains the expected files.
- [ ] The output is stored and shared securely.
- [ ] Anonymisation was not enabled with the current script.

## Example commands

Assess one project:

```powershell
& "./GCP Sizer.ps1" -Projects "my-test-project-id"
```

Assess several explicitly selected projects:

```powershell
& "./GCP Sizer.ps1" -Projects "project-id-1,project-id-2,project-id-3"
```

Assess projects listed in a text file:

```powershell
& "./GCP Sizer.ps1" -ProjectFile "./projects.txt"
```

Assess all projects visible to the authenticated identity:

```powershell
& "./GCP Sizer.ps1" -GetAllProjects
```
