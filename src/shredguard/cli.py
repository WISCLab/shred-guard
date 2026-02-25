"""Command-line interface for ShredGuard."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from . import __version__
from .config import Config, ConfigError
from .fixer import PrefixCollisionError, apply_fixes, check_prefix_collisions
from .gitignore import GitignoreFilter
from .output import Formatter
from .scanner import scan_files


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


if __name__ == "__main__":
    main()
