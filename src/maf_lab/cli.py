"""Command-line interface for MAF Agent Reliability Lab."""

import click

from maf_lab import __version__


@click.group()
@click.version_option(version=__version__, prog_name="maf-lab")
def main() -> None:
    """MAF Agent Reliability Lab: statistically aware, MAF-native regression and adversarial reliability harness.

    This tool provides:
    - Deterministic scenario execution against MAF agents
    - Typed fake tools with canonical state management
    - Four-level evaluations (tool, turn, session, system)
    - Reliability statistics with confidence intervals
    - Fault injection and recovery testing
    - Adversarial injection testing
    - Paired baseline/candidate comparison
    - Evidence export and replay

    For detailed documentation, see the specification in docs/spec/03-maf-agent-reliability-lab.md
    """
    pass


@main.command()
def validate() -> None:
    """Validate scenario manifests and configurations.

    Checks schemas, version compatibility, split discipline, and cross-split constraints.
    """
    click.echo("validate: not yet implemented")


@main.command()
@click.option("--suite", type=str, default=None, help="Suite name (development, regression)")
@click.option("--scenario", type=str, default=None, help="Single scenario ID to run")
@click.option("--agent", type=str, required=True, help="Agent config file path")
@click.option("--trials", type=int, default=1, help="Number of trials to run")
@click.option("--output", type=str, default=None, help="Output directory for artifacts")
@click.option("--offline", is_flag=True, help="Run offline (no external services)")
@click.option("--faults", is_flag=True, help="Enable fault injection")
def run(
    suite: str | None,
    scenario: str | None,
    agent: str,
    trials: int,
    output: str | None,
    offline: bool,
    faults: bool,
) -> None:
    """Execute scenario trials against an agent configuration.

    Specify either --suite (development, regression) or --scenario (single scenario_id).
    """
    click.echo("run: not yet implemented")


@main.command()
@click.argument("artifact_dir", type=str)
def evaluate(artifact_dir: str) -> None:
    """Re-evaluate completed trial evidence without rerunning the model.

    Runs deterministic evaluators over immutable evidence artifacts.
    """
    click.echo("evaluate: not yet implemented")


@main.command()
@click.argument("baseline_dir", type=str)
@click.argument("candidate_dir", type=str)
@click.option("--paired", is_flag=True, help="Use paired bootstrap comparison")
@click.option("--output", type=str, default=None, help="Output directory for comparison results")
def compare(baseline_dir: str, candidate_dir: str, paired: bool, output: str | None) -> None:
    """Compare baseline and candidate configurations on matched trials.

    Computes paired deltas, discordant counts, and confidence intervals.
    """
    click.echo("compare: not yet implemented")


@main.command()
@click.argument("experiment_dir", type=str)
@click.option("--format", type=str, default="markdown,json", help="Output formats: markdown, json, junit")
def report(experiment_dir: str, format: str) -> None:
    """Generate reports from experiment results.

    Produces Markdown, JSON, and/or JUnit formats from canonical artifacts.
    """
    click.echo("report: not yet implemented")


@main.command()
@click.argument("artifact_dir", type=str)
def recover(artifact_dir: str) -> None:
    """Scan and recover partial artifacts from incomplete runs.

    Validates hashes, classifies recovery status, and marks for resumption.
    """
    click.echo("recover: not yet implemented")


@main.command()
@click.option("--host", type=str, default="127.0.0.1", help="Bind host")
@click.option("--port", type=int, default=8000, help="Bind port")
def serve(host: str, port: int) -> None:
    """Start the optional FastAPI service.

    Provides REST API for experiment submission, status, and replay.
    """
    click.echo("serve: not yet implemented")


if __name__ == "__main__":
    main()
