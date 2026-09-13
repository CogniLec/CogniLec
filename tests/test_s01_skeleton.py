"""S01 — Repository, Tooling & CI Skeleton verification tests."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


class TestDirectoryStructure:
    """Verify the monorepo directory layout exists."""

    @pytest.mark.unit
    def test_src_directory_exists(self) -> None:
        assert ROOT.joinpath("src").is_dir()

    @pytest.mark.unit
    def test_src_init_exists(self) -> None:
        assert ROOT.joinpath("src", "__init__.py").is_file()

    @pytest.mark.unit
    def test_py_typed_marker_exists(self) -> None:
        assert ROOT.joinpath("src", "py.typed").is_file()

    @pytest.mark.unit
    def test_migrations_directory_exists(self) -> None:
        assert ROOT.joinpath("migrations").is_dir()

    @pytest.mark.unit
    def test_notebooks_directory_exists(self) -> None:
        assert ROOT.joinpath("notebooks").is_dir()

    @pytest.mark.unit
    def test_docker_directory_exists(self) -> None:
        assert ROOT.joinpath("docker").is_dir()

    @pytest.mark.unit
    def test_config_directory_exists(self) -> None:
        assert ROOT.joinpath("config").is_dir()

    @pytest.mark.unit
    def test_tests_directory_exists(self) -> None:
        assert ROOT.joinpath("tests").is_dir()

    @pytest.mark.unit
    def test_scripts_directory_exists(self) -> None:
        assert ROOT.joinpath("scripts").is_dir()

    @pytest.mark.unit
    def test_docs_adrs_directory_exists(self) -> None:
        assert ROOT.joinpath("docs", "adrs").is_dir()


class TestPyprojectToml:
    """Verify pyproject.toml configuration per spec."""

    @pytest.mark.unit
    def test_file_exists(self) -> None:
        assert ROOT.joinpath("pyproject.toml").is_file()

    @pytest.mark.unit
    def test_ruff_line_length(self) -> None:
        import tomllib

        with open(ROOT / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        assert data["tool"]["ruff"]["line-length"] == 100

    @pytest.mark.unit
    def test_ruff_target_version(self) -> None:
        import tomllib

        with open(ROOT / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        assert data["tool"]["ruff"]["target-version"] == "py312"

    @pytest.mark.unit
    def test_ruff_select_rules(self) -> None:
        import tomllib

        with open(ROOT / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        select = data["tool"]["ruff"]["lint"]["select"]
        for rule in ["E", "F", "I", "N", "UP", "W", "C4", "PTH", "PIE", "T20", "TRY", "SIM", "RUF"]:
            assert rule in select, f"Missing ruff rule: {rule}"

    @pytest.mark.unit
    def test_ruff_format_double_quotes(self) -> None:
        import tomllib

        with open(ROOT / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        assert data["tool"]["ruff"]["format"]["quote-style"] == "double"

    @pytest.mark.unit
    def test_mypy_strict(self) -> None:
        import tomllib

        with open(ROOT / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        mypy = data["tool"]["mypy"]
        assert mypy["strict"] is True
        assert mypy["python_version"] == "3.12"
        assert mypy["warn_return_any"] is True
        assert mypy["disallow_any_generics"] is True

    @pytest.mark.unit
    def test_pytest_config(self) -> None:
        import tomllib

        with open(ROOT / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        pytest_cfg = data["tool"]["pytest"]["ini_options"]
        markers_str = " ".join(pytest_cfg["markers"])
        assert "unit" in markers_str
        assert "integration" in markers_str
        assert pytest_cfg["asyncio_mode"] == "auto"
        assert pytest_cfg["testpaths"] == ["tests"]

    @pytest.mark.unit
    def test_requires_python(self) -> None:
        import tomllib

        with open(ROOT / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        rp = data["project"]["requires-python"]
        assert "3.12" in rp


class TestPreCommitConfig:
    """Verify .pre-commit-config.yaml has all required hooks."""

    @pytest.mark.unit
    def test_file_exists(self) -> None:
        assert ROOT.joinpath(".pre-commit-config.yaml").is_file()

    @pytest.mark.unit
    def test_ruff_hook(self) -> None:
        import yaml

        with open(ROOT / ".pre-commit-config.yaml") as f:
            data = yaml.safe_load(f)
        repos = [r["repo"] for r in data["repos"]]
        assert "https://github.com/astral-sh/ruff-pre-commit" in repos

    @pytest.mark.unit
    def test_mypy_hook(self) -> None:
        import yaml

        with open(ROOT / ".pre-commit-config.yaml") as f:
            data = yaml.safe_load(f)
        repos = [r["repo"] for r in data["repos"]]
        assert "https://github.com/pre-commit/mirrors-mypy" in repos

    @pytest.mark.unit
    def test_gitleaks_hook(self) -> None:
        import yaml

        with open(ROOT / ".pre-commit-config.yaml") as f:
            data = yaml.safe_load(f)
        repos = [r["repo"] for r in data["repos"]]
        assert "https://github.com/gitleaks/gitleaks" in repos

    @pytest.mark.unit
    def test_sqlfluff_hook(self) -> None:
        import yaml

        with open(ROOT / ".pre-commit-config.yaml") as f:
            data = yaml.safe_load(f)
        repos = [r["repo"] for r in data["repos"]]
        assert "https://github.com/sqlfluff/sqlfluff" in repos


class TestCIGithubActions:
    """Verify GitHub Actions CI workflow."""

    @pytest.mark.unit
    def test_ci_file_exists(self) -> None:
        assert ROOT.joinpath(".github", "workflows", "ci.yml").is_file()

    @pytest.mark.unit
    def test_lint_job_exists(self) -> None:
        import yaml

        with open(ROOT / ".github" / "workflows" / "ci.yml") as f:
            data = yaml.safe_load(f)
        assert "lint-and-typecheck" in data["jobs"]

    @pytest.mark.unit
    def test_gitleaks_job_exists(self) -> None:
        import yaml

        with open(ROOT / ".github" / "workflows" / "ci.yml") as f:
            data = yaml.safe_load(f)
        assert "gitleaks" in data["jobs"]

    @pytest.mark.unit
    def test_unit_tests_job_exists(self) -> None:
        import yaml

        with open(ROOT / ".github" / "workflows" / "ci.yml") as f:
            data = yaml.safe_load(f)
        assert "unit-tests" in data["jobs"]

    @pytest.mark.unit
    def test_integration_tests_job_exists(self) -> None:
        import yaml

        with open(ROOT / ".github" / "workflows" / "ci.yml") as f:
            data = yaml.safe_load(f)
        assert "integration-tests" in data["jobs"]

    @pytest.mark.unit
    def test_docker_build_job_exists(self) -> None:
        import yaml

        with open(ROOT / ".github" / "workflows" / "ci.yml") as f:
            data = yaml.safe_load(f)
        assert "docker-build" in data["jobs"]

    @pytest.mark.unit
    def test_cuda_matrix_job_exists(self) -> None:
        import yaml

        with open(ROOT / ".github" / "workflows" / "ci.yml") as f:
            data = yaml.safe_load(f)
        assert "cuda-matrix-check" in data["jobs"]

    @pytest.mark.unit
    def test_lint_job_runs_ruff_and_mypy(self) -> None:
        import yaml

        with open(ROOT / ".github" / "workflows" / "ci.yml") as f:
            data = yaml.safe_load(f)
        steps = data["jobs"]["lint-and-typecheck"]["steps"]
        step_names = [s["name"].lower() for s in steps]
        assert any("ruff" in n for n in step_names)
        assert any("mypy" in n for n in step_names)


class TestADRs:
    """Verify all 18 ADRs exist per spec."""

    @pytest.mark.unit
    def test_template_exists(self) -> None:
        assert ROOT.joinpath("docs", "adrs", "template.md").is_file()

    @pytest.mark.unit
    def test_eighteen_adr_files(self) -> None:
        adrs = list(ROOT.joinpath("docs", "adrs").glob("0*.md"))
        assert len(adrs) == 18

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "adr_id,title",
        [
            ("001", "Prefect"),
            ("002", "Worker Pool"),
            ("003", "Event-Driven"),
            ("004", "Dual PostgreSQL"),
            ("005", "Partitioning"),
            ("006", "TextTiling"),
            ("007", "LLM Agents"),
            ("008", "Visual Enrichment"),
            ("009", "Diarisation"),
            ("010", "Topic Identity"),
            ("011", "GPU"),
            ("012", "Fine-Tuning"),
            ("013", "Row-Level Security"),
            ("014", "Two-Phase"),
            ("015", "VRAM"),
            ("016", "Hybrid LLM"),
            ("017", "8-Bit"),
            ("018", "Local-First"),
        ],
    )
    def test_adr_file_contains_title_keyword(self, adr_id: str, title: str) -> None:
        adr_path = ROOT.joinpath("docs", "adrs")
        matches = list(adr_path.glob(f"{adr_id}-*.md"))
        assert len(matches) == 1, f"Expected exactly one ADR-{adr_id}, found {len(matches)}"
        content = matches[0].read_text()
        assert title.lower() in content.lower(), f"ADR-{adr_id} missing keyword: {title}"


class TestEnvAndSops:
    """Verify .env.example and .sops.yaml exist with correct content."""

    @pytest.mark.unit
    def test_env_example_exists(self) -> None:
        assert ROOT.joinpath(".env.example").is_file()

    @pytest.mark.unit
    def test_env_example_has_required_vars(self) -> None:
        content = ROOT.joinpath(".env.example").read_text()
        required = ["POSTGRES_PASSWORD", "MINIO_ROOT_PASSWORD", "SECRET_KEY", "TRAEFIK_EMAIL"]
        for var in required:
            assert var in content, f"Missing env var: {var}"

    @pytest.mark.unit
    def test_sops_yaml_exists(self) -> None:
        assert ROOT.joinpath(".sops.yaml").is_file()

    @pytest.mark.unit
    def test_sops_yaml_has_creation_rules(self) -> None:
        import yaml

        with open(ROOT / ".sops.yaml") as f:
            data = yaml.safe_load(f)
        assert "creation_rules" in data
        assert len(data["creation_rules"]) > 0


class TestGitignore:
    """Verify .gitignore covers essentials."""

    @pytest.mark.unit
    def test_gitignore_exists(self) -> None:
        assert ROOT.joinpath(".gitignore").is_file()

    @pytest.mark.unit
    def test_gitignore_covers_venv(self) -> None:
        content = ROOT.joinpath(".gitignore").read_text()
        assert ".venv/" in content

    @pytest.mark.unit
    def test_gitignore_covers_env(self) -> None:
        content = ROOT.joinpath(".gitignore").read_text()
        assert ".env" in content

    @pytest.mark.unit
    def test_gitignore_covers_mypy_cache(self) -> None:
        content = ROOT.joinpath(".gitignore").read_text()
        assert ".mypy_cache/" in content

    @pytest.mark.unit
    def test_gitignore_covers_ruff_cache(self) -> None:
        content = ROOT.joinpath(".gitignore").read_text()
        assert ".ruff_cache/" in content


class TestSrcPyTyped:
    """Verify src/ is properly typed for mypy strict."""

    @pytest.mark.unit
    def test_src_init_is_empty_or_minimal(self) -> None:
        content = ROOT.joinpath("src", "__init__.py").read_text()
        assert len(content) < 100, "src/__init__.py should be minimal"

    @pytest.mark.unit
    def test_py_typed_is_empty_marker(self) -> None:
        content = ROOT.joinpath("src", "py.typed").read_text()
        assert len(content) == 0, "py.typed should be an empty marker file"
