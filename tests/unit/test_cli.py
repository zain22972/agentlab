"""Unit tests for CLI functionality."""

from click.testing import CliRunner

from maf_lab.cli import main


def test_cli_version() -> None:
    """Test that the CLI reports version correctly."""
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "maf-lab" in result.output


def test_cli_help() -> None:
    """Test that the CLI help command works."""
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "MAF Agent Reliability Lab" in result.output
    assert "Usage:" in result.output


def test_cli_validate_command_exists() -> None:
    """Test that validate command is available."""
    runner = CliRunner()
    result = runner.invoke(main, ["validate", "--help"])
    assert result.exit_code == 0
    assert "validate" in result.output.lower()


def test_cli_run_command_exists() -> None:
    """Test that run command is available."""
    runner = CliRunner()
    result = runner.invoke(main, ["run", "--help"])
    assert result.exit_code == 0
    assert "run" in result.output.lower()


def test_cli_evaluate_command_exists() -> None:
    """Test that evaluate command is available."""
    runner = CliRunner()
    result = runner.invoke(main, ["evaluate", "--help"])
    assert result.exit_code == 0
    assert "evaluate" in result.output.lower()


def test_cli_compare_command_exists() -> None:
    """Test that compare command is available."""
    runner = CliRunner()
    result = runner.invoke(main, ["compare", "--help"])
    assert result.exit_code == 0
    assert "compare" in result.output.lower()


def test_cli_report_command_exists() -> None:
    """Test that report command is available."""
    runner = CliRunner()
    result = runner.invoke(main, ["report", "--help"])
    assert result.exit_code == 0
    assert "report" in result.output.lower()


def test_cli_recover_command_exists() -> None:
    """Test that recover command is available."""
    runner = CliRunner()
    result = runner.invoke(main, ["recover", "--help"])
    assert result.exit_code == 0
    assert "recover" in result.output.lower()


def test_cli_serve_command_exists() -> None:
    """Test that serve command is available."""
    runner = CliRunner()
    result = runner.invoke(main, ["serve", "--help"])
    assert result.exit_code == 0
    assert "serve" in result.output.lower()
