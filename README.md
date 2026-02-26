# ShredGuard by [WISC Lab](https://kidspeech.wisc.edu/)

[![CI](https://github.com/WiscLab/shred-guard/actions/workflows/ci.yml/badge.svg)](https://github.com/WISCLab/shred-guard/actions/workflows/ci.yml) [![CD](https://github.com/WISCLab/shred-guard/actions/workflows/cd.yml/badge.svg)](https://github.com/WISCLab/shred-guard/actions/workflows/cd.yml)

Scan files for PHI (Protected Health Information) patterns and replace them with deterministic pseudonyms. Integrates seamlessly with pre-commit hooks.


## Appendix

- [Value Proposition](https://raw.githubusercontent.com/WiscLab/shred-guard/main/value-proposition.svg)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Commands](#commands)
  - [shredguard init](#shredguard-init)
  - [shredguard check](#shredguard-check)
  - [shredguard fix](#shredguard-fix)
- [Configuration](#configuration)
- [Pre-commit](#pre-commit)
- [Reference](#reference)
  - [CLI Options](#cli-options)
  - [Configuration Reference](#configuration-reference)
  - [Built-in Pattern Suggestions](#built-in-pattern-suggestions)
  - [Exit Codes](#exit-codes)
  - [Binary File Handling](#binary-file-handling)
- [License](#license)

## Installation

```bash
pip install shred-guard
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

Replacements are deterministic: and the same value always gets the same pseudonym within a run.

## Configuration

Configuration lives in `pyproject.toml` (or `/*/*.toml` set with --config):

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

## Reference

### CLI Options

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

### Configuration Reference

```toml
[[tool.shredguard.patterns]]
regex = "SUB-\\d{4,6}"        # Required: regex pattern
description = "Subject ID"     # Optional: shown in output
files = ["*.csv", "data/**"]   # Optional: only scan matching files
exclude_files = ["*_test.*"]   # Optional: skip matching files
```

### Built-in Pattern Suggestions

When running `shredguard init`, you can choose from these common patterns:

| Pattern | Description |
|---------|-------------|
| `SUB-\d{4,6}` | Subject ID |
| `\b\d{3}-\d{2}-\d{4}\b` | Social Security Number |
| `MRN\d{6,10}` | Medical Record Number |
| `[email pattern]` | Email addresses |
| `[phone pattern]` | Phone numbers (10 digits) |
| `\b\d{5}(?:-\d{4})?\b` | ZIP codes |

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success (no matches found for `check`) |
| `1` | Matches found or error |

### Binary File Handling

Binary files are automatically detected and skipped (null byte check in first 8KB). Use `--verbose` to see skipped files.

## License

[MIT](https://github.com/WiscLab/shred-guard/blob/main/LICENSE)
