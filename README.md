# ShredGuard

A CLI tool to scan files for configurable regex patterns (PHI identifiers) and optionally replace matches with deterministic pseudonyms. Integrates with pre-commit framework.

## Features

- Scan files for PHI patterns using configurable regex
- Replace matches with deterministic pseudonyms (same value = same ID)
- Pre-commit integration for automated checks
- Respects `.gitignore` patterns
- Ruff-style output format (`file:line:col: SGxxx Message`)
- Cross-platform support (Windows, macOS, Linux)

## Installation

```bash
pip install shredguard
```

Or install from source:

```bash
pip install -e .
```

## Quick Start

1. Add configuration to your `pyproject.toml`:

```toml
[tool.shredguard]
[[tool.shredguard.patterns]]
regex = "SUB-\\d{4,6}"
description = "Subject ID"

[[tool.shredguard.patterns]]
regex = "\\b\\d{3}-\\d{2}-\\d{4}\\b"
description = "SSN-like pattern"

[[tool.shredguard.patterns]]
regex = "MRN\\d{6,10}"
description = "Medical Record Number"
```

2. Run a check:

```bash
shredguard check .
```

3. Fix (replace) found patterns:

```bash
shredguard fix --prefix REDACTED .
```

## Pre-commit Setup

Add to your `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/shredguard/shredguard
    rev: v0.1.0
    hooks:
      - id: shredguard-check
```

Or to automatically fix:

```yaml
repos:
  - repo: https://github.com/shredguard/shredguard
    rev: v0.1.0
    hooks:
      - id: shredguard-fix
        args: [--prefix, REDACTED]
```

## CLI Reference

### `shredguard check`

Scan files for PHI patterns.

```bash
shredguard check [OPTIONS] [FILES]...
```

**Arguments:**
- `FILES` - Files or directories to scan (default: current directory)

**Options:**
- `--all-files` - Scan all files (typically used with pre-commit)
- `--no-gitignore` - Don't respect `.gitignore` patterns
- `--config PATH` - Path to config file (default: searches for `pyproject.toml`)
- `--verbose, -v` - Show verbose output (skipped files, etc.)

**Exit codes:**
- `0` - No matches found
- `1` - Matches found or error

### `shredguard fix`

Replace PHI patterns with pseudonyms.

```bash
shredguard fix [OPTIONS] [FILES]...
```

**Arguments:**
- `FILES` - Files or directories to scan and fix (default: current directory)

**Options:**
- `--prefix PREFIX` - Prefix for pseudonyms (default: `REDACTED`)
- `--output-map PATH` - Write JSON mapping of originals to pseudonyms
- `--all-files` - Scan all files
- `--no-gitignore` - Don't respect `.gitignore` patterns
- `--config PATH` - Path to config file
- `--verbose, -v` - Show verbose output

## Configuration Reference

Configuration is read from `pyproject.toml` under the `[tool.shredguard]` section.

### Patterns

Define patterns to scan for:

```toml
[[tool.shredguard.patterns]]
regex = "SUB-\\d{4,6}"        # Required: regex pattern
description = "Subject ID"     # Optional: description for output
files = ["*.csv", "data/**"]   # Optional: only scan matching files
exclude_files = ["*_test.*"]   # Optional: exclude matching files
```

**Pattern fields:**
- `regex` (required) - Regular expression pattern to match
- `description` (optional) - Human-readable description shown in output
- `files` (optional) - List of glob patterns; only scan files matching these
- `exclude_files` (optional) - List of glob patterns; skip files matching these

### Pattern Codes

Patterns are assigned stable codes (SG001, SG002, etc.) based on their order in the config file.

## Example Workflow

1. Create test files with PHI:

```bash
echo "Patient SUB-1234 was enrolled on 2024-01-15" > patient_notes.txt
echo "SSN: 123-45-6789" >> patient_notes.txt
```

2. Check for PHI:

```bash
$ shredguard check patient_notes.txt
patient_notes.txt:1:9: SG001 Subject ID [SUB-1234]
patient_notes.txt:2:6: SG002 SSN-like pattern [123-45-6789]

Found 2 matches in 1 file
```

3. Replace PHI with pseudonyms:

```bash
$ shredguard fix --prefix ANON --output-map mapping.json patient_notes.txt
Replaced 2 occurrences of 2 unique values in 1 file
Mapping written to: mapping.json
```

4. Verify replacement:

```bash
$ cat patient_notes.txt
Patient ANON-0 was enrolled on 2024-01-15
SSN: ANON-1

$ cat mapping.json
{
  "SUB-1234": "ANON-0",
  "123-45-6789": "ANON-1"
}
```

## Deterministic Replacement

ShredGuard uses deterministic pseudonym assignment:
- The same matched value always gets the same pseudonym within a single run
- IDs are assigned in order of first encounter (0, 1, 2, ...)
- The mapping can be saved to a JSON file for reference

## Binary File Detection

Binary files are automatically detected and skipped using a null byte heuristic (checking first 8KB). Use `--verbose` to see which files are skipped.

## Development

Install development dependencies:

```bash
pip install -e ".[dev]"
```

Run tests:

```bash
pytest
```

## License

MIT
