"""Unit tests for `maf-lab run`: single-scenario offline B0 execution (issue #3, AC1).

`--scenario` takes a path to a scenario manifest file (YAML or JSON), `--agent`
selects the driving agent (only `b0` exists today), and `--output` is the
artifact root `ArtifactWriter` commits under. This is deliberately not the
full manifest validator (#7): loading here is `yaml.safe_load` followed by
`ScenarioManifest.model_validate`, with no schema-version dispatch, split
discipline, or cross-scenario checks.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from maf_lab.cli import main

SCENARIO_YAML = """
schema_version: "1.0"
scenario_id: refund.eligible.single.v1
family_id: refund.eligible
title: Eligible customer requests a partial refund
split: regression
risk: high
fixture_version: refund-fixtures-1.0
initial_state:
  clock: "2026-02-01T12:00:00Z"
  authenticated_principal:
    customer_id: cus_001
    scopes: [refund:create, order:read]
  customers:
    - {customer_id: cus_001, name: "Example Customer", region: US, verified: true}
  orders:
    - order_id: ord_100
      customer_id: cus_001
      status: delivered
      currency: USD
      paid_minor: 5000
      refundable_minor: 5000
      purchased_at: "2026-01-25T10:00:00Z"
oracle:
  required_tool_calls:
    - name: create_refund
      args_subset:
        order_id: ord_100
        amount_minor: 2000
        currency: USD
        reason: damaged
  state_assertions:
    - {path: "orders[ord_100].refundable_minor", op: eq, value: 3000, severity: critical}
"""


def write_scenario(tmp_path: Path) -> Path:
    path = tmp_path / "refund.eligible.single.v1.yaml"
    path.write_text(SCENARIO_YAML, encoding="utf-8")
    return path


def test_run_executes_one_scenario_offline_and_exits_zero(tmp_path: Path) -> None:
    scenario_path = write_scenario(tmp_path)
    output_dir = tmp_path / "artifacts"
    runner = CliRunner()

    result = runner.invoke(
        main,
        [
            "run",
            "--scenario",
            str(scenario_path),
            "--agent",
            "b0",
            "--output",
            str(output_dir),
            "--offline",
        ],
    )

    assert result.exit_code == 0, result.output
    assert (output_dir / "trial_0001" / "COMMITTED").exists()


def test_run_prints_the_committed_trial_directory(tmp_path: Path) -> None:
    scenario_path = write_scenario(tmp_path)
    output_dir = tmp_path / "artifacts"
    runner = CliRunner()

    result = runner.invoke(
        main,
        ["run", "--scenario", str(scenario_path), "--agent", "b0", "--output", str(output_dir)],
    )

    assert str(output_dir / "trial_0001") in result.output


def test_run_fails_with_a_nonzero_exit_code_for_a_missing_scenario_file(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "run",
            "--scenario",
            str(tmp_path / "does-not-exist.yaml"),
            "--agent",
            "b0",
            "--output",
            str(tmp_path / "artifacts"),
        ],
    )
    assert result.exit_code != 0


def test_run_fails_for_an_unsupported_agent(tmp_path: Path) -> None:
    scenario_path = write_scenario(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "run",
            "--scenario",
            str(scenario_path),
            "--agent",
            "b2",
            "--output",
            str(tmp_path / "artifacts"),
        ],
    )
    assert result.exit_code != 0
    assert "b2" in result.output


def test_run_requires_either_scenario_or_suite(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        main, ["run", "--agent", "b0", "--output", str(tmp_path / "artifacts")]
    )
    assert result.exit_code != 0


def test_run_rejects_malformed_yaml(tmp_path: Path) -> None:
    scenario_path = tmp_path / "bad.yaml"
    scenario_path.write_text("not: [valid, closing", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "run",
            "--scenario",
            str(scenario_path),
            "--agent",
            "b0",
            "--output",
            str(tmp_path / "artifacts"),
        ],
    )
    assert result.exit_code != 0


def test_run_a_scenario_whose_critical_assertion_fails_exits_nonzero(tmp_path: Path) -> None:
    broken = yaml.safe_load(SCENARIO_YAML)
    broken["oracle"]["state_assertions"][0]["value"] = 9999
    scenario_path = tmp_path / "broken.yaml"
    scenario_path.write_text(yaml.safe_dump(broken), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "run",
            "--scenario",
            str(scenario_path),
            "--agent",
            "b0",
            "--output",
            str(tmp_path / "artifacts"),
        ],
    )
    assert result.exit_code != 0
