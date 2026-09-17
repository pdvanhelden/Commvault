#!/usr/bin/env python3
"""AWS EBS snapshot inventory and TCO assessment.

Reports all account-owned EBS snapshots, classifies candidates, and calculates
transparent cost upper bounds from logical GiB and caller-supplied regional rates.
Safe by default: this script never deletes resources.

Python >= 3.10. Dependency: boto3
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

LOG = logging.getLogger("aws-snapshot-tco")
SDK_CONFIG = Config(retries={"max_attempts": 10, "mode": "adaptive"})


@dataclass
class Finding:
    account_id: str
    region: str
    snapshot_id: str
    volume_id: str
    source_volume_exists: bool
    referenced_by_ami: bool
    snapshot_tier: str
    start_time_utc: str
    age_days: int
    logical_size_gib: int
    estimated_billable_gib: str
    price_per_gib_month: str
    estimated_monthly_cost: str
    estimated_annual_cost: str
    currency: str
    classification: str
    rationale: str
    encrypted: bool
    owner_id: str
    description: str
    tags_json: str
    estimate_basis: str


def args_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--profile", action="append", help="AWS CLI profile. Repeat for multiple profiles.")
    p.add_argument("--role-arn", action="append", help="Role ARN to assume from each base profile. Repeatable.")
    p.add_argument("--external-id", help="ExternalId used by AssumeRole.")
    p.add_argument("--regions", nargs="+", help="Regions to scan. Default: all enabled regions.")
    p.add_argument("--min-age-days", type=int, default=90, help="Minimum age for Potentially Orphaned.")
    p.add_argument("--high-confidence-age-days", type=int, default=180)
    p.add_argument("--include-tag", action="append", default=[], metavar="KEY[=VALUE]",
                   help="Only classify matched snapshots as candidates. Repeatable.")
    p.add_argument("--protect-tag", action="append", default=[], metavar="KEY[=VALUE]",
                   help="Always classify matches as Recovery Candidate. Repeatable.")
    p.add_argument("--rates-json", help="JSON file mapping region to per-GiB-month rate, with optional 'default'.")
    p.add_argument("--default-rate", type=Decimal, help="Fallback per-GiB-month rate.")
    p.add_argument("--currency", default="USD")
    p.add_argument("--utilization-percent", type=Decimal, default=Decimal("100"),
                   help="Assumed billable fraction of logical size. Use 100 for an upper bound.")
    p.add_argument("--output", default="aws_snapshot_tco.csv")
    p.add_argument("--summary-output", default="aws_snapshot_tco_summary.json")
    p.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO")
    return p


def tag_rules(values: Iterable[str]) -> list[tuple[str, str | None]]:
    parsed = []
    for item in values:
        key, sep, value = item.partition("=")
        if not key.strip():
            raise ValueError("Tag key must not be empty")
        parsed.append((key, value if sep else None))
    return parsed


def matches(tags: dict[str, str], rules: list[tuple[str, str | None]]) -> bool:
    return any(k in tags and (v is None or tags[k] == v) for k, v in rules)


def load_rates(path: str | None, default: Decimal | None) -> dict[str, Decimal]:
    rates: dict[str, Decimal] = {}
    if path:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("rates JSON must be an object")
        for key, value in raw.items():
            try:
                rates[str(key)] = Decimal(str(value))
            except InvalidOperation as exc:
                raise ValueError(f"Invalid rate for {key}: {value}") from exc
    if default is not None:
        rates.setdefault("default", default)
    return rates


def assumed_session(base: boto3.Session, arn: str, external_id: str | None) -> boto3.Session:
    request = {"RoleArn": arn, "RoleSessionName": "snapshot-tco-assessment"}
    if external_id:
        request["ExternalId"] = external_id
    result = base.client("sts", config=SDK_CONFIG).assume_role(**request)["Credentials"]
    return boto3.Session(
        aws_access_key_id=result["AccessKeyId"],
        aws_secret_access_key=result["SecretAccessKey"],
        aws_session_token=result["SessionToken"],
    )


def paginator_items(client, operation: str, result_key: str, **kwargs) -> list[dict]:
    items: list[dict] = []
    for page in client.get_paginator(operation).paginate(**kwargs):
        items.extend(page.get(result_key, []))
    return items


def enabled_regions(session: boto3.Session) -> list[str]:
    client = session.client("ec2", region_name=session.region_name or "us-east-1", config=SDK_CONFIG)
    return sorted(item["RegionName"] for item in client.describe_regions(AllRegions=False)["Regions"])


def classify(*, volume_exists: bool, ami_reference: bool, age: int, tags: dict[str, str],
             min_age: int, high_age: int, include, protect) -> tuple[str, str]:
    if ami_reference:
        return "Active", "snapshot_referenced_by_private_ami"
    if volume_exists:
        return "Active", "source_volume_exists"
    if protect and matches(tags, protect):
        return "Recovery Candidate", "source_missing_but_protection_tag_matches"
    if include and not matches(tags, include):
        return "Recovery Candidate", "source_missing_but_required_candidate_tag_missing"
    if age < min_age:
        return "Recovery Candidate", "source_missing_but_snapshot_is_younger_than_threshold"
    if age >= high_age and not tags:
        return "High Confidence Orphan", "source_missing_no_ami_no_tags_and_high_age_threshold_met"
    return "Potentially Orphaned", "source_missing_no_ami_and_minimum_age_met"


def scan(session: boto3.Session, args, rates, include, protect) -> tuple[list[Finding], list[str]]:
    account = session.client("sts", config=SDK_CONFIG).get_caller_identity()["Account"]
    findings: list[Finding] = []
    errors: list[str] = []
    now = datetime.now(timezone.utc)
    utilization = args.utilization_percent / Decimal("100")

    for region in args.regions or enabled_regions(session):
        LOG.info("Scanning account=%s region=%s", account, region)
        ec2 = session.client("ec2", region_name=region, config=SDK_CONFIG)
        try:
            volume_ids = {v["VolumeId"] for v in paginator_items(ec2, "describe_volumes", "Volumes")}
            images = paginator_items(ec2, "describe_images", "Images", Owners=["self"])
            ami_snapshots = {
                mapping["Ebs"]["SnapshotId"]
                for image in images
                for mapping in image.get("BlockDeviceMappings", [])
                if mapping.get("Ebs", {}).get("SnapshotId")
            }
            snapshots = paginator_items(ec2, "describe_snapshots", "Snapshots", OwnerIds=["self"])
        except (ClientError, BotoCoreError) as exc:
            message = f"{account}/{region}: {exc}"
            LOG.error(message)
            errors.append(message)
            continue

        rate = rates.get(region, rates.get("default"))
        for snap in snapshots:
            snapshot_id = snap["SnapshotId"]
            volume_id = snap.get("VolumeId", "")
            volume_exists = bool(volume_id and volume_id in volume_ids)
            ami_ref = snapshot_id in ami_snapshots
            created = snap["StartTime"].astimezone(timezone.utc)
            age = max(0, (now - created).days)
            tags = {t.get("Key", ""): t.get("Value", "") for t in snap.get("Tags", [])}
            classification, rationale = classify(
                volume_exists=volume_exists, ami_reference=ami_ref, age=age, tags=tags,
                min_age=args.min_age_days, high_age=args.high_confidence_age_days,
                include=include, protect=protect,
            )
            logical = int(snap.get("VolumeSize", 0))
            estimated_billable = Decimal(logical) * utilization
            monthly = estimated_billable * rate if rate is not None else None
            findings.append(Finding(
                account_id=account, region=region, snapshot_id=snapshot_id,
                volume_id=volume_id, source_volume_exists=volume_exists,
                referenced_by_ami=ami_ref, snapshot_tier=snap.get("StorageTier", "standard"),
                start_time_utc=created.isoformat(), age_days=age, logical_size_gib=logical,
                estimated_billable_gib=f"{estimated_billable:.2f}",
                price_per_gib_month="" if rate is None else f"{rate:.8f}",
                estimated_monthly_cost="" if monthly is None else f"{monthly:.2f}",
                estimated_annual_cost="" if monthly is None else f"{monthly * 12:.2f}",
                currency=args.currency, classification=classification, rationale=rationale,
                encrypted=bool(snap.get("Encrypted")), owner_id=snap.get("OwnerId", ""),
                description=snap.get("Description", ""), tags_json=json.dumps(tags, sort_keys=True),
                estimate_basis=f"logical_size_gib x {args.utilization_percent}% x supplied_rate; not incremental billed bytes",
            ))
    return findings, errors


def write_output(findings: list[Finding], errors: list[str], args) -> None:
    rows = [asdict(item) for item in findings]
    with Path(args.output).open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(Finding.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(rows)

    candidate_classes = {"Potentially Orphaned", "High Confidence Orphan"}
    candidates = [r for r in rows if r["classification"] in candidate_classes]
    def total(field: str) -> str:
        return f"{sum(Decimal(r[field]) for r in candidates if r[field] != ''):.2f}"
    summary = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "currency": args.currency,
        "estimate_disclaimer": "Directional estimate based on logical snapshot size and utilization assumption; EBS snapshots are incremental, so this is not actual billed storage or guaranteed savings.",
        "inventory_count": len(rows),
        "candidate_count": len(candidates),
        "candidate_logical_size_gib": sum(r["logical_size_gib"] for r in candidates),
        "candidate_estimated_billable_gib": total("estimated_billable_gib"),
        "candidate_estimated_monthly_cost": total("estimated_monthly_cost"),
        "candidate_estimated_annual_cost": total("estimated_annual_cost"),
        "classification_counts": {name: sum(r["classification"] == name for r in rows) for name in sorted({r["classification"] for r in rows})},
        "scan_errors": errors,
    }
    Path(args.summary_output).write_text(json.dumps(summary, indent=2), encoding="utf-8")


def main() -> int:
    args = args_parser().parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(message)s")
    if args.min_age_days < 0 or args.high_confidence_age_days < args.min_age_days:
        raise SystemExit("Age thresholds are invalid")
    if not Decimal("0") <= args.utilization_percent <= Decimal("100"):
        raise SystemExit("--utilization-percent must be between 0 and 100")
    rates = load_rates(args.rates_json, args.default_rate)
    include, protect = tag_rules(args.include_tag), tag_rules(args.protect_tag)
    sessions: list[boto3.Session] = []
    for profile in args.profile or [None]:
        base = boto3.Session(profile_name=profile)
        sessions.extend(assumed_session(base, arn, args.external_id) for arn in args.role_arn) if args.role_arn else sessions.append(base)
    findings: list[Finding] = []
    errors: list[str] = []
    for session in sessions:
        batch, batch_errors = scan(session, args, rates, include, protect)
        findings.extend(batch)
        errors.extend(batch_errors)
    write_output(findings, errors, args)
    LOG.info("Wrote %s and %s", args.output, args.summary_output)
    return 2 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
