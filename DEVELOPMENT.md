# Development Guide

## Pre-commit Hooks Setup

This project uses pre-commit hooks to maintain code quality and catch issues before they reach CI/CD.

### Installation

```bash
# Activate virtual environment
source .venv/bin/activate

# Install pre-commit
pip install pre-commit

# Install git hooks
pre-commit install
```

### Automatic Hooks (Run on Every Commit)

These hooks run automatically when you commit:

1. **File Checks**
   - Remove trailing whitespace
   - Fix end of files (ensure newline at EOF)
   - Check YAML, JSON, TOML syntax
   - Detect large files (>1MB)
   - Detect private keys
   - Check for merge conflicts

2. **Black** - Code formatter
   - Line length: 100 characters
   - Python 3.11+ target
   - Auto-formats on commit

3. **Ruff** - Fast Python linter
   - Import sorting (isort replacement)
   - Linting rules: E, F, W, I, N, UP, B, C4
   - Auto-fixes issues when possible

### Manual Hooks (Run When Needed)

These hooks are expensive and run only when explicitly requested:

```bash
# Run mypy type checking
pre-commit run --hook-stage manual mypy --all-files

# Run bandit security scanning
pre-commit run --hook-stage manual bandit --all-files

# Run dependency security check (requires network)
pre-commit run --hook-stage manual python-safety-dependencies-check --all-files
```

### Running Hooks Manually

```bash
# Run all automatic hooks on all files
pre-commit run --all-files

# Run specific hook
pre-commit run black --all-files
pre-commit run ruff --all-files

# Run on specific files
pre-commit run --files app/main.py tests/test_auth.py

# Update hook versions
pre-commit autoupdate
```

### Bypassing Hooks (Emergency Only)

If you absolutely need to commit without running hooks:

```bash
git commit --no-verify -m "Emergency commit message"
```

**Warning:** Only use this in emergencies. The CI will still fail if issues exist.

## Code Quality Standards

### Formatting
- **Black**: Line length 100, Python 3.11+ target
- **Import ordering**: Automatic via Ruff (isort-compatible)

### Linting
- **Ruff rules enabled**:
  - `E` - pycodestyle errors
  - `F` - pyflakes
  - `W` - pycodestyle warnings
  - `I` - isort (import sorting)
  - `N` - pep8-naming
  - `UP` - pyupgrade
  - `B` - flake8-bugbear
  - `C4` - flake8-comprehensions

- **Ignored rules**:
  - `E501` - Line too long (handled by Black)
  - `B008` - Function calls in argument defaults (FastAPI Depends pattern)
  - `B904` - Exception chaining (can be added later)

- **Per-file exceptions**:
  - `app/main.py` - E402 (imports after logging setup)
  - `tests/conftest.py` - E402 (imports after env setup)

### Type Checking
- **mypy**: Configured with `warn_return_any`, `warn_unused_configs`
- **Ignore missing imports**: True (for external packages without stubs)

### Security
- **bandit**: Configured to skip test directories and alembic migrations
- **B101**: Assert statements allowed (used in tests)

## CI/CD Integration

The pre-commit hooks match the CI/CD pipeline exactly:

### Lint Job (GitHub Actions)
```yaml
- name: Check formatting with Black
  run: black --check .

- name: Lint with Ruff
  run: ruff check .
```

Running pre-commit hooks locally ensures these checks pass before pushing.

## Common Issues and Solutions

### "would reformat" error
```bash
# Let Black reformat the files
black .

# Or run pre-commit to auto-fix
pre-commit run black --all-files
```

### Ruff import sorting errors
```bash
# Auto-fix import sorting
ruff check --fix .

# Or let pre-commit handle it
pre-commit run ruff --all-files
```

### E402 (Module level import not at top)
This is intentional in `app/main.py` (logging setup) and `tests/conftest.py` (env setup).
These files are excluded via `[tool.ruff.lint.per-file-ignores]` in `pyproject.toml`.

### Pre-commit hook fails but manual command works
```bash
# Clean pre-commit cache and reinstall
pre-commit clean
pre-commit install --install-hooks
pre-commit run --all-files
```

## Development Workflow

1. **Before starting work**: Pull latest changes
   ```bash
   git pull origin main
   ```

2. **Make changes**: Edit code normally

3. **Test changes**: Run relevant tests
   ```bash
   pytest tests/test_module/
   ```

4. **Commit**: Hooks run automatically
   ```bash
   git add .
   git commit -m "Add new feature"
   # Pre-commit hooks run here
   ```

5. **If hooks fail**: Fix issues and recommit
   ```bash
   # Hooks auto-fixed some issues, stage them
   git add .
   git commit -m "Add new feature"
   ```

6. **Push**: CI runs same checks
   ```bash
   git push origin feature/branch-name
   ```

## Tips for Success

1. **Run hooks early**: Don't wait until commit time
   ```bash
   pre-commit run --all-files
   ```

2. **Keep hooks updated**: Run occasionally
   ```bash
   pre-commit autoupdate
   ```

3. **Check before large refactors**: Avoid fixing hundreds of files
   ```bash
   # Format everything first
   black .
   ruff check --fix .
   ```

4. **Use editor integration**: Configure your editor to run Black/Ruff on save
   - VSCode: Python extension with Black formatter
   - PyCharm: Black plugin + Ruff external tool
   - Vim/Neovim: ALE or coc-pyright with formatters

5. **Understand the rules**: Read error messages carefully
   ```bash
   # Get detailed info about a rule
   ruff rule E402
   ruff rule B008
   ```
