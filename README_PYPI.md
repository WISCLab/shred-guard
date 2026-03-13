[![GitHub](https://img.shields.io/badge/GitHub-WISCLab%2Fshred--guard-181717?logo=github)](https://github.com/WiscLab/shred-guard)

Scan files for PHI (Protected Health Information) patterns and replace them with deterministic pseudonyms. Integrates seamlessly with pre-commit hooks.

## Installation

```bash
pip install shred-guard
# or with uv
uv add shred-guard
```

## Quick Start

Run the interactive setup wizard:

```bash
shredguard init
```

This walks you through:
- Selecting PHI patterns to detect (SSNs, emails, MRNs, custom patterns)
- Configuring file restrictions
- Setting up pre-commit hooks

## Commands

### `shredguard init`

Interactive setup wizard. Creates your configuration and optionally sets up pre-commit integration.

### `shredguard check`

Scan for PHI patterns:

```bash
shredguard check .                    # Scan current directory
shredguard check data/ notes.txt     # Scan specific paths
```

Output uses ruff-style formatting:
```
patient_notes.txt:1:9: SG001 Subject ID [SUB-1234]
patient_notes.txt:2:6: SG002 SSN [123-45-6789]
```

### `shredguard fix`

Replace PHI with pseudonyms:

```bash
shredguard fix .                                    # Replace with REDACTED-0, REDACTED-1, ...
shredguard fix --prefix ANON .                     # Custom prefix: ANON-0, ANON-1, ...
shredguard fix --output-map mapping.json .         # Save original -> pseudonym mapping
```

Replacements are deterministic: the same value always gets the same pseudonym within a run.

### `shredguard audit`

Scan every commit on every local branch for PHI patterns:

```bash
shredguard audit                          # Audit all local branches
shredguard audit --include-remotes        # Also scan remote-tracking branches
shredguard audit --output report.json     # Custom output file path
```

Configuration and `.gitignore` are locked to the current working-tree state so results are reproducible. The config and `.gitignore` files must have no uncommitted changes before running. Output is written to a timestamped JSON file (`shredguard-audit-<timestamp>.json`).

## Configuration

Configuration lives in `pyproject.toml` (or a standalone `shredguard.toml`):

```toml
[tool.shredguard]

[[tool.shredguard.patterns]]
regex = "SUB-\\d{4,6}"
description = "Subject ID"

[[tool.shredguard.patterns]]
regex = "\\b\\d{3}-\\d{2}-\\d{4}\\b"
description = "SSN"
```

Each pattern can optionally include `files` and `exclude_files` globs to control which files are scanned.

## Pre-commit

Add to `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: local
    hooks:
      - id: shredguard-check
        name: shredguard check
        entry: shredguard check
        language: system
        types: [text]
```

Or let `shredguard init` set this up for you.

## CLI Reference

**`shredguard check [OPTIONS] [FILES]...`**

| Option | Description |
|--------|-------------|
| `--all-files` | Scan all files recursively |
| `--no-gitignore` | Don't respect `.gitignore` patterns |
| `--config PATH` | Path to config file |
| `-v, --verbose` | Show verbose output (skipped files, etc.) |

**`shredguard fix [OPTIONS] [FILES]...`**

| Option | Description |
|--------|-------------|
| `--prefix TEXT` | Prefix for pseudonyms (default: `REDACTED`) |
| `--output-map PATH` | Write JSON mapping of originals to pseudonyms |
| `--all-files` | Scan all files recursively |
| `--no-gitignore` | Don't respect `.gitignore` patterns |
| `--config PATH` | Path to config file |
| `-v, --verbose` | Show verbose output |

**`shredguard audit [OPTIONS]`**

| Option | Description |
|--------|-------------|
| `--include-remotes` | Also scan remote-tracking branches |
| `--output PATH` | Path for audit JSON output (default: `shredguard-audit-<timestamp>.json`) |
| `--no-gitignore` | Don't respect `.gitignore` patterns |
| `--config PATH` | Path to config file |
| `-v, --verbose` | Show verbose output (skipped binary files, etc.) |

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success (no matches found) |
| `1` | Matches found or error |

## License

[MIT](https://github.com/WiscLab/shred-guard/blob/main/LICENSE)
