from __future__ import annotations

import argparse
import json

from iris_persistence.migrations import (
    MigrationError,
    MigrationPlan,
    UnsafeMigrationError,
    _load_model_spec,
    apply_plan,
    check_drift,
    create_plan,
    rollback_backup,
    verify_plan,
)


def _cmd_plan(args: argparse.Namespace) -> int:
    plan = create_plan(
        [_load_model_spec(spec) for spec in args.models],
        target_revision=args.to,
        from_revision=args.from_revision,
        fail_on_drift=args.fail_on_drift,
    )
    if args.out:
        plan.save(args.out)
    if args.json:
        print(plan.to_json())
    else:
        print(f"Plan {plan.current_revision or '<base>'} -> {plan.target_revision}")
        for operation in plan.operations:
            marker = "!" if operation.safety != "safe" else "+"
            print(f"{marker} {operation.classname} {operation.op_type} {operation.path}")
        if args.out:
            print(f"Saved plan to {args.out}")
    return 0


def _cmd_apply(args: argparse.Namespace) -> int:
    if args.plan_file:
        plan = MigrationPlan.load(args.plan_file)
    else:
        plan = create_plan(
            [_load_model_spec(spec) for spec in args.models],
            target_revision=args.to,
            from_revision=args.from_revision,
            fail_on_drift=args.fail_on_drift,
        )
    result = apply_plan(
        plan,
        backup_dir=args.backup_dir,
        allow_destructive=args.allow_destructive or args.yes,
    )
    if args.json:
        print(json.dumps(result.to_dict(), sort_keys=True, indent=2, default=str))
    else:
        print(f"{result.status}: {result.target_revision}")
        if result.backup_dir:
            print(f"Backup: {result.backup_dir}")
    return 2 if result.status == "blocked" else 0


def _cmd_review_plan(args: argparse.Namespace) -> int:
    plan = MigrationPlan.load(args.plan_file)
    if args.json:
        print(plan.to_json())
    else:
        print(f"Plan {plan.current_revision or '<base>'} -> {plan.target_revision}")
        for operation in plan.operations:
            marker = "!" if operation.safety != "safe" else "+"
            print(
                f"{marker} {operation.safety} "
                f"{operation.classname} {operation.op_type} {operation.path}"
            )
    return 0


def _cmd_verify_plan(args: argparse.Namespace) -> int:
    result = verify_plan(MigrationPlan.load(args.plan_file))
    if args.json:
        print(json.dumps(result.to_dict(), sort_keys=True, indent=2, default=str))
    else:
        print("Converged." if result.converged else "Not converged.")
        for diff in result.diffs:
            print(diff)
    return 0 if result.converged else 2


def _cmd_rollback_backup(args: argparse.Namespace) -> int:
    result = rollback_backup(
        args.backup_dir,
        allow_destructive=args.allow_destructive or args.yes,
    )
    if args.json:
        print(json.dumps(result.to_dict(), sort_keys=True, indent=2, default=str))
    else:
        print(f"Rolled back backup {result.backup_dir}")
    return 0


def _cmd_drift(args: argparse.Namespace) -> int:
    report = check_drift([_load_model_spec(spec) for spec in args.models])
    if args.json:
        print(json.dumps(report.to_dict(), sort_keys=True, indent=2, default=str))
    else:
        if report.has_drift:
            for diff in report.diffs:
                print(diff)
        else:
            print("No drift.")
    return 2 if report.has_drift and args.fail_on_drift else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="iris-persistence")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan")
    plan.add_argument("models", nargs="+", help="Model specs in module:Class form")
    plan.add_argument("--to", dest="to")
    plan.add_argument("--from", dest="from_revision")
    plan.add_argument("--json", action="store_true")
    plan.add_argument("--out")
    plan.add_argument("--dry-run", action="store_true", help="Accepted for workflow symmetry")
    plan.add_argument("--fail-on-drift", action=argparse.BooleanOptionalAction, default=True)
    plan.set_defaults(func=_cmd_plan)

    apply = subparsers.add_parser("apply")
    apply.add_argument("models", nargs="*", help="Model specs in module:Class form")
    apply.add_argument("--plan-file")
    apply.add_argument("--to", dest="to")
    apply.add_argument("--from", dest="from_revision")
    apply.add_argument("--json", action="store_true")
    apply.add_argument("--backup-dir", default=".iris_persistence/backups")
    apply.add_argument("--allow-destructive", action="store_true")
    apply.add_argument("--dry-run", action="store_true", help="Accepted for workflow symmetry")
    apply.add_argument("--fail-on-drift", action=argparse.BooleanOptionalAction, default=True)
    apply.add_argument("--yes", action="store_true")
    apply.set_defaults(func=_cmd_apply)

    review_plan = subparsers.add_parser("review-plan")
    review_plan.add_argument("plan_file")
    review_plan.add_argument("--json", action="store_true")
    review_plan.set_defaults(func=_cmd_review_plan)

    apply_plan_cmd = subparsers.add_parser("apply-plan")
    apply_plan_cmd.add_argument("plan_file")
    apply_plan_cmd.add_argument("--backup-dir", default=".iris_persistence/backups")
    apply_plan_cmd.add_argument("--allow-destructive", action="store_true")
    apply_plan_cmd.add_argument("--yes", action="store_true")
    apply_plan_cmd.add_argument("--json", action="store_true")
    apply_plan_cmd.set_defaults(
        func=lambda args: _cmd_apply(
            argparse.Namespace(
                plan_file=args.plan_file,
                models=[],
                to=None,
                from_revision=None,
                fail_on_drift=True,
                backup_dir=args.backup_dir,
                allow_destructive=args.allow_destructive,
                yes=args.yes,
                json=args.json,
            )
        )
    )

    verify_plan_cmd = subparsers.add_parser("verify-plan")
    verify_plan_cmd.add_argument("plan_file")
    verify_plan_cmd.add_argument("--json", action="store_true")
    verify_plan_cmd.set_defaults(func=_cmd_verify_plan)

    rollback_backup_cmd = subparsers.add_parser("rollback-backup")
    rollback_backup_cmd.add_argument("backup_dir")
    rollback_backup_cmd.add_argument("--allow-destructive", action="store_true")
    rollback_backup_cmd.add_argument("--yes", action="store_true")
    rollback_backup_cmd.add_argument("--json", action="store_true")
    rollback_backup_cmd.set_defaults(func=_cmd_rollback_backup)

    drift = subparsers.add_parser("drift")
    drift.add_argument("models", nargs="+", help="Model specs in module:Class form")
    drift.add_argument("--json", action="store_true")
    drift.add_argument("--fail-on-drift", action=argparse.BooleanOptionalAction, default=True)
    drift.set_defaults(func=_cmd_drift)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except UnsafeMigrationError as exc:
        parser.exit(2, f"{exc}\n")
    except MigrationError as exc:
        parser.exit(1, f"{exc}\n")
    except Exception as exc:
        parser.exit(1, f"{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
