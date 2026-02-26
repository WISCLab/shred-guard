"""Command-line interface for ShredGuard."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import click

from . import __version__
from .config import Config, ConfigError
from .fixer import PrefixCollisionError, apply_fixes, check_prefix_collisions
from .gitignore import GitignoreFilter
from .output import Formatter
from .scanner import scan_files


# Common PHI patterns that users can choose from
COMMON_PATTERNS = [
    {
        "regex": r"SUB-\d{4,6}",
        "description": "Subject ID (SUB-XXXX format)",
    },
    {
        "regex": r"\b\d{3}-\d{2}-\d{4}\b",
        "description": "SSN (Social Security Number)",
    },
    {
        "regex": r"MRN\d{6,10}",
        "description": "Medical Record Number (MRN format)",
    },
    {
        "regex": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        "description": "Email addresses",
    },
    {
        "regex": r"\b\d{10}\b|\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b",
        "description": "Phone numbers (10 digits)",
    },
    {
        "regex": r"\b\d{5}(?:-\d{4})?\b",
        "description": "ZIP codes (5 or 9 digit)",
    },
]


def collect_files(
    paths: tuple[Path, ...],
    all_files: bool,
    gitignore_filter: GitignoreFilter,
) -> list[Path]:
    """Collect files to scan from the given paths.

    Args:
        paths: Paths specified by the user.
        all_files: If True, scan all files recursively.
        gitignore_filter: Filter for .gitignore patterns.

    Returns:
        List of files to scan.
    """
    files: list[Path] = []

    for path in paths:
        if path.is_file():
            if not gitignore_filter.is_ignored(path):
                files.append(path)
        elif path.is_dir():
            if all_files:
                # Recursively collect all files
                for file_path in path.rglob("*"):
                    if file_path.is_file() and not gitignore_filter.is_ignored(
                        file_path
                    ):
                        files.append(file_path)
            else:
                # Only collect files directly passed (not recursive by default)
                # When a directory is passed without --all-files, we still scan it
                for file_path in path.rglob("*"):
                    if file_path.is_file() and not gitignore_filter.is_ignored(
                        file_path
                    ):
                        files.append(file_path)

    return sorted(set(files))


@click.group()
@click.version_option(version=__version__, prog_name="shredguard")
def main() -> None:
    """ShredGuard: Scan and redact PHI identifiers from files."""
    pass


@main.command()
@click.argument(
    "files",
    nargs=-1,
    type=click.Path(exists=True, path_type=Path),
)
@click.option(
    "--all-files",
    is_flag=True,
    help="Scan all files (typically used with pre-commit).",
)
@click.option(
    "--no-gitignore",
    is_flag=True,
    help="Don't respect .gitignore patterns.",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, path_type=Path),
    help="Path to config file (default: pyproject.toml).",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Show verbose output (skipped files, etc.).",
)
def check(
    files: tuple[Path, ...],
    all_files: bool,
    no_gitignore: bool,
    config_path: Path | None,
    verbose: bool,
) -> None:
    """Scan files for PHI patterns.

    FILES are the files or directories to scan. If not specified,
    scans the current directory.
    """
    formatter = Formatter()

    # Load configuration
    try:
        config = Config.load(config_path)
    except ConfigError as e:
        click.echo(formatter.format_error(str(e)), err=True)
        sys.exit(1)

    # Default to current directory if no files specified
    if not files:
        files = (Path("."),)

    # Set up gitignore filter - use the first directory/file's parent as base
    # for finding .gitignore files
    first_path = files[0]
    if first_path.is_dir():
        base_path = first_path.resolve()
    else:
        base_path = first_path.parent.resolve()
    gitignore_filter = GitignoreFilter(base_path, respect_gitignore=not no_gitignore)

    # Collect files to scan
    file_list = collect_files(files, all_files, gitignore_filter)

    if not file_list:
        click.echo(formatter.format_warning("No files to scan"))
        sys.exit(0)

    # Scan files
    matches, binary_files = scan_files(file_list, config.patterns, verbose=verbose)

    # Show verbose output for skipped binary files
    if verbose and binary_files:
        for bf in binary_files:
            click.echo(formatter.format_verbose_binary_skip(bf), err=True)

    # Output matches
    if matches:
        click.echo(formatter.format_matches(matches, base_path))
        click.echo()

    # Output summary
    files_with_matches = len({m.file for m in matches})
    click.echo(
        formatter.format_check_summary(
            len(matches), files_with_matches, len(config.patterns)
        )
    )

    # Exit with error if matches found
    sys.exit(1 if matches else 0)


@main.command()
@click.argument(
    "files",
    nargs=-1,
    type=click.Path(exists=True, path_type=Path),
)
@click.option(
    "--all-files",
    is_flag=True,
    help="Scan all files (typically used with pre-commit).",
)
@click.option(
    "--no-gitignore",
    is_flag=True,
    help="Don't respect .gitignore patterns.",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, path_type=Path),
    help="Path to config file (default: pyproject.toml).",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Show verbose output (skipped files, etc.).",
)
@click.option(
    "--prefix",
    default="REDACTED",
    show_default=True,
    help="Prefix for replacement pseudonyms.",
)
@click.option(
    "--output-map",
    type=click.Path(path_type=Path),
    help="Path to write JSON mapping of original values to pseudonyms.",
)
def fix(
    files: tuple[Path, ...],
    all_files: bool,
    no_gitignore: bool,
    config_path: Path | None,
    verbose: bool,
    prefix: str,
    output_map: Path | None,
) -> None:
    """Replace PHI patterns with pseudonyms.

    FILES are the files or directories to scan and fix. If not specified,
    scans the current directory.
    """
    formatter = Formatter()

    # Load configuration
    try:
        config = Config.load(config_path)
    except ConfigError as e:
        click.echo(formatter.format_error(str(e)), err=True)
        sys.exit(1)

    # Default to current directory if no files specified
    if not files:
        files = (Path("."),)

    # Set up gitignore filter - use the first directory/file's parent as base
    # for finding .gitignore files
    first_path = files[0]
    if first_path.is_dir():
        base_path = first_path.resolve()
    else:
        base_path = first_path.parent.resolve()
    gitignore_filter = GitignoreFilter(base_path, respect_gitignore=not no_gitignore)

    # Collect files to scan
    file_list = collect_files(files, all_files, gitignore_filter)

    if not file_list:
        click.echo(formatter.format_warning("No files to scan"))
        sys.exit(0)

    # Check for prefix collisions in ALL files before scanning for patterns
    collisions = check_prefix_collisions(file_list, prefix)
    if collisions:
        click.echo(
            formatter.format_prefix_collision_error(
                PrefixCollisionError(prefix, collisions)
            ),
            err=True,
        )
        sys.exit(1)

    # Scan files
    matches, binary_files = scan_files(file_list, config.patterns, verbose=verbose)

    # Show verbose output for skipped binary files
    if verbose and binary_files:
        for bf in binary_files:
            click.echo(formatter.format_verbose_binary_skip(bf), err=True)

    if not matches:
        click.echo(formatter.format_fix_summary(
            type("FixResult", (), {
                "total_replacements": 0,
                "unique_values": 0,
                "files_modified": 0,
            })()
        ))
        sys.exit(0)

    # Apply fixes
    try:
        result = apply_fixes(matches, prefix, output_map)
    except PrefixCollisionError as e:
        click.echo(formatter.format_prefix_collision_error(e), err=True)
        sys.exit(1)

    # Output summary
    click.echo(formatter.format_fix_summary(result))

    if output_map:
        click.echo(f"Mapping written to: {output_map}")


@main.command()
def init() -> None:
    """Initialize ShredGuard in your project.

    Interactive setup wizard that creates configuration and
    optionally sets up pre-commit hooks.
    """
    formatter = Formatter()

    # Step 1: Welcome
    click.echo()
    click.secho("=" * 50, fg="cyan")
    click.secho("  Welcome to ShredGuard Setup", fg="cyan", bold=True)
    click.secho("=" * 50, fg="cyan")
    click.echo()
    click.echo("This wizard will help you:")
    click.echo("  1. Configure PHI patterns to detect")
    click.echo("  2. Set up pre-commit hooks (optional)")
    click.echo()

    if not click.confirm("Ready to begin?", default=True):
        click.echo("Setup cancelled.")
        sys.exit(0)

    click.echo()

    # Step 2: Choose config file location
    click.secho("Step 1: Configuration File", fg="yellow", bold=True)
    click.echo("-" * 30)
    click.echo()
    click.echo("Where would you like to store the ShredGuard config?")
    click.echo()
    click.echo("  [1] pyproject.toml (recommended - keeps all config in one place)")
    click.echo("  [2] shredguard.toml (standalone config file)")
    click.echo()

    config_choice = click.prompt(
        "Your choice",
        type=click.IntRange(1, 2),
        default=1,
    )

    config_path = Path("pyproject.toml") if config_choice == 1 else Path("shredguard.toml")
    click.echo(f"\n  -> Using: {config_path}")
    click.echo()

    # Step 3: Select PHI patterns
    click.secho("Step 2: PHI Patterns to Detect", fg="yellow", bold=True)
    click.echo("-" * 30)
    click.echo()
    click.echo("Select the PHI patterns you want to detect.")
    click.echo("You can add custom patterns afterward.")
    click.echo()

    selected_patterns = []

    for i, pattern in enumerate(COMMON_PATTERNS, 1):
        click.echo(f"  [{i}] {pattern['description']}")
        click.secho(f"      regex: {pattern['regex']}", fg="bright_black")

        if click.confirm(f"      Include this pattern?", default=True):
            selected_patterns.append(pattern.copy())
        click.echo()

    # Step 4: Add custom patterns
    click.secho("Step 3: Custom Patterns (Optional)", fg="yellow", bold=True)
    click.echo("-" * 30)
    click.echo()

    while True:
        if not click.confirm("Would you like to add a custom pattern?", default=False):
            break

        click.echo()
        description = click.prompt("  Pattern description (e.g., 'Patient ID')")
        regex = click.prompt("  Regex pattern")

        # Validate the regex
        try:
            re.compile(regex)
            selected_patterns.append({
                "regex": regex,
                "description": description,
            })
            click.secho(f"  -> Added: {description}", fg="green")
        except re.error as e:
            click.secho(f"  -> Invalid regex: {e}", fg="red")
            click.echo("     Pattern not added. Try again.")

        click.echo()

    if not selected_patterns:
        click.secho("\nNo patterns selected!", fg="red")
        if not click.confirm("Continue with no patterns? (You can add them later)", default=False):
            click.echo("Setup cancelled.")
            sys.exit(1)

    click.echo()

    # Step 5: File restrictions (optional)
    click.secho("Step 4: File Restrictions (Optional)", fg="yellow", bold=True)
    click.echo("-" * 30)
    click.echo()
    click.echo("You can restrict which files are scanned.")
    click.echo("Leave blank to scan all text files.")
    click.echo()

    include_files = None
    exclude_files = None

    if click.confirm("Do you want to restrict scanning to specific file patterns?", default=False):
        click.echo()
        click.echo("Enter glob patterns separated by commas.")
        click.echo("Examples: *.csv, *.txt, data/**/*.json")
        click.echo()
        include_input = click.prompt("  Include patterns", default="").strip()
        if include_input:
            include_files = [p.strip() for p in include_input.split(",") if p.strip()]
            click.secho(f"  -> Will scan: {include_files}", fg="green")

    click.echo()

    if click.confirm("Do you want to exclude specific file patterns?", default=False):
        click.echo()
        click.echo("Enter glob patterns separated by commas.")
        click.echo("Examples: *_test.py, tests/**, README.md")
        click.echo()
        exclude_input = click.prompt("  Exclude patterns", default="").strip()
        if exclude_input:
            exclude_files = [p.strip() for p in exclude_input.split(",") if p.strip()]
            click.secho(f"  -> Will exclude: {exclude_files}", fg="green")

    click.echo()

    # Step 6: Generate and write config
    click.secho("Step 5: Creating Configuration", fg="yellow", bold=True)
    click.echo("-" * 30)
    click.echo()

    config_content = _generate_config_content(
        selected_patterns, include_files, exclude_files, config_choice == 1
    )

    # Check if file exists and has existing content
    if config_path.exists():
        if config_choice == 1:  # pyproject.toml
            existing = config_path.read_text()
            if "[tool.shredguard]" in existing:
                click.secho(f"  ! {config_path} already has ShredGuard config", fg="yellow")
                if not click.confirm("  Overwrite existing ShredGuard section?", default=False):
                    click.echo("  Keeping existing config.")
                else:
                    # Remove existing shredguard section and add new one
                    _update_pyproject_toml(config_path, config_content)
                    click.secho(f"  -> Updated: {config_path}", fg="green")
            else:
                # Append to existing pyproject.toml
                with open(config_path, "a") as f:
                    f.write("\n" + config_content)
                click.secho(f"  -> Updated: {config_path}", fg="green")
        else:  # shredguard.toml
            click.secho(f"  ! {config_path} already exists", fg="yellow")
            if not click.confirm("  Overwrite?", default=False):
                click.echo("  Keeping existing config.")
            else:
                config_path.write_text(config_content)
                click.secho(f"  -> Created: {config_path}", fg="green")
    else:
        config_path.write_text(config_content)
        click.secho(f"  -> Created: {config_path}", fg="green")

    click.echo()

    # Step 7: Pre-commit setup
    click.secho("Step 6: Pre-commit Integration", fg="yellow", bold=True)
    click.echo("-" * 30)
    click.echo()
    click.echo("ShredGuard can run automatically before each commit")
    click.echo("to prevent accidentally committing PHI.")
    click.echo()

    if click.confirm("Set up pre-commit hook?", default=True):
        _setup_precommit(formatter)
    else:
        click.echo("  Skipping pre-commit setup.")
        click.echo("  You can run 'shredguard check' manually anytime.")

    click.echo()

    # Step 8: Done!
    click.secho("=" * 50, fg="green")
    click.secho("  Setup Complete!", fg="green", bold=True)
    click.secho("=" * 50, fg="green")
    click.echo()
    click.echo("Next steps:")
    click.echo("  1. Review your config in " + str(config_path))
    click.echo("  2. Run 'shredguard check' to scan your files")
    click.echo("  3. Run 'shredguard fix' to redact any PHI found")
    click.echo()


def _generate_config_content(
    patterns: list[dict],
    include_files: list[str] | None,
    exclude_files: list[str] | None,
    is_pyproject: bool,
) -> str:
    """Generate TOML config content."""
    lines = []

    if is_pyproject:
        lines.append("[tool.shredguard]")
    else:
        lines.append("# ShredGuard Configuration")
        lines.append("# https://github.com/your-org/shredguard")
        lines.append("")
        lines.append("[tool.shredguard]")

    lines.append("")

    for pattern in patterns:
        lines.append("[[tool.shredguard.patterns]]")
        # Escape backslashes for TOML
        escaped_regex = pattern["regex"].replace("\\", "\\\\")
        lines.append(f'regex = "{escaped_regex}"')
        lines.append(f'description = "{pattern["description"]}"')

        if include_files:
            files_str = ", ".join(f'"{f}"' for f in include_files)
            lines.append(f"files = [{files_str}]")

        if exclude_files:
            exclude_str = ", ".join(f'"{f}"' for f in exclude_files)
            lines.append(f"exclude_files = [{exclude_str}]")

        lines.append("")

    return "\n".join(lines)


def _update_pyproject_toml(path: Path, new_shredguard_content: str) -> None:
    """Update pyproject.toml by replacing existing ShredGuard section."""
    content = path.read_text()

    # Find and remove existing [tool.shredguard] section
    # This is a simple approach - for complex cases, use tomlkit
    lines = content.split("\n")
    new_lines = []
    in_shredguard_section = False

    for line in lines:
        if line.strip().startswith("[tool.shredguard]"):
            in_shredguard_section = True
            continue
        elif line.strip().startswith("[[tool.shredguard."):
            in_shredguard_section = True
            continue
        elif in_shredguard_section:
            # Check if we've hit a new section
            if line.strip().startswith("[") and not line.strip().startswith("[[tool.shredguard"):
                in_shredguard_section = False
                new_lines.append(line)
        else:
            new_lines.append(line)

    # Remove trailing empty lines and add the new content
    while new_lines and not new_lines[-1].strip():
        new_lines.pop()

    new_lines.append("")
    new_lines.append(new_shredguard_content)

    path.write_text("\n".join(new_lines))


def _setup_precommit(formatter: Formatter) -> None:
    """Set up pre-commit hooks for ShredGuard."""
    precommit_config_path = Path(".pre-commit-config.yaml")

    # Check if pre-commit is installed
    try:
        subprocess.run(
            ["pre-commit", "--version"],
            capture_output=True,
            check=True,
        )
        precommit_installed = True
    except (subprocess.CalledProcessError, FileNotFoundError):
        precommit_installed = False

    if not precommit_installed:
        click.echo()
        click.secho("  ! pre-commit is not installed", fg="yellow")
        click.echo("  Install it with: pip install pre-commit")
        click.echo()
        if not click.confirm("  Continue setting up config anyway?", default=True):
            return

    # Generate pre-commit config content
    shredguard_hook = """  - repo: local
    hooks:
      - id: shredguard-check
        name: shredguard check
        entry: shredguard check
        language: system
        types: [text]
"""

    click.echo()

    if precommit_config_path.exists():
        existing = precommit_config_path.read_text()

        if "shredguard" in existing.lower():
            click.secho("  -> .pre-commit-config.yaml already has ShredGuard", fg="green")
        else:
            click.echo("  Found existing .pre-commit-config.yaml")
            click.echo()
            click.echo("  Add this to your repos section:")
            click.echo()
            click.secho(shredguard_hook, fg="cyan")

            if click.confirm("  Automatically add to file?", default=True):
                # Simple append approach - add to repos list
                if "repos:" in existing:
                    # Find the repos: line and add after it
                    lines = existing.split("\n")
                    new_lines = []
                    added = False

                    for i, line in enumerate(lines):
                        new_lines.append(line)
                        if line.strip() == "repos:" and not added:
                            # Add our hook after repos:
                            new_lines.append(shredguard_hook.rstrip())
                            added = True

                    precommit_config_path.write_text("\n".join(new_lines))
                    click.secho("  -> Updated: .pre-commit-config.yaml", fg="green")
                else:
                    # No repos section, append
                    with open(precommit_config_path, "a") as f:
                        f.write("\nrepos:\n" + shredguard_hook)
                    click.secho("  -> Updated: .pre-commit-config.yaml", fg="green")
            else:
                click.echo("  Please add it manually.")
    else:
        # Create new config
        new_config = f"repos:\n{shredguard_hook}"
        precommit_config_path.write_text(new_config)
        click.secho("  -> Created: .pre-commit-config.yaml", fg="green")

    # Offer to run pre-commit install
    click.echo()
    if precommit_installed:
        if click.confirm("  Run 'pre-commit install' to activate hooks?", default=True):
            try:
                result = subprocess.run(
                    ["pre-commit", "install"],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    click.secho("  -> Git hooks installed!", fg="green")
                else:
                    click.secho(f"  ! Error: {result.stderr}", fg="red")
            except Exception as e:
                click.secho(f"  ! Error running pre-commit: {e}", fg="red")


if __name__ == "__main__":
    main()
