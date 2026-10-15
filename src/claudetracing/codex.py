"""Codex CLI tracing configuration following @mlflow/codex conventions."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from pydantic import AliasChoices, BaseModel, ConfigDict, Field
import tomlkit

MLFLOW_CODEX_NOTIFY = ["mlflow-codex", "notify-hook"]
TRACING_CONFIG_FILENAME = "mlflow-tracing.json"
CONFIG_TOML_FILENAME = "config.toml"


class CodexTracingConfig(BaseModel):
    """Schema for .codex/mlflow-tracing.json consumed by @mlflow/codex."""

    model_config = ConfigDict(populate_by_name=True)

    tracking_uri: str = Field(
        validation_alias=AliasChoices("trackingUri", "tracking_uri"),
        serialization_alias="trackingUri",
    )
    experiment_id: str = Field(
        default="0",
        validation_alias=AliasChoices("experimentId", "experiment_id"),
        serialization_alias="experimentId",
    )
    trace_location: str | None = Field(
        default=None,
        validation_alias=AliasChoices("traceLocation", "trace_location"),
        serialization_alias="traceLocation",
    )
    tracking_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("trackingToken", "tracking_token"),
        serialization_alias="trackingToken",
    )


class CodexStatus(BaseModel):
    """Current Codex tracing status."""

    enabled: bool
    tracking_uri: str | None = None
    experiment_id: str | None = None
    trace_location: str | None = None
    scope: str = "none"
    config_path: Path | None = None
    binary_installed: bool = False


def codex_home() -> Path:
    """Resolve the user-level Codex home directory ($CODEX_HOME or ~/.codex)."""
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).resolve()


def resolve_codex_dir(
    project_root: Path | None = None, *, project_local: bool = True
) -> Path:
    """Resolve the target .codex directory (project-local ./.codex or ~/.codex)."""
    if project_local:
        root = (project_root or Path.cwd()).resolve()
        return root / ".codex"
    return codex_home()


def is_mlflow_codex_installed() -> bool:
    """Return True if the `mlflow-codex` CLI binary is available on PATH."""
    return shutil.which("mlflow-codex") is not None


def _is_sky_computer_use_notify(notify_value: object) -> bool:
    """Return True if `notify` is Codex Desktop's SkyComputerUseClient wrapper."""
    if not isinstance(notify_value, list) or not notify_value:
        return False
    return "SkyComputerUseClient" in str(notify_value[0])


def _is_owned_notify(notify_value: object) -> bool:
    """Return True if a `notify` array invokes @mlflow/codex or claudetracing.codex."""
    if not isinstance(notify_value, list):
        return False
    items = [str(x) for x in notify_value]
    return any(
        "mlflow-codex" in item or "claudetracing.codex" in item for item in items
    )


def _write_notify_to_toml(
    config_path: Path,
    *,
    strict_custom: bool = True,
    notify_cmd: list[str] | None = None,
) -> None:
    """Ensure `notify` is configured in a TOML config file."""
    target_cmd = notify_cmd or MLFLOW_CODEX_NOTIFY
    config_path.parent.mkdir(parents=True, exist_ok=True)
    original = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    doc = tomlkit.parse(original) if original.strip() else tomlkit.document()

    existing_notify = doc.get("notify")
    if _is_sky_computer_use_notify(existing_notify):
        items = [str(x) for x in existing_notify]  # type: ignore[union-attr]
        new_items = list(items)
        prev_json = json.dumps(target_cmd)
        if "--previous-notify" in new_items:
            idx = new_items.index("--previous-notify")
            if idx + 1 < len(new_items):
                existing_prev = new_items[idx + 1]
                if (
                    "mlflow-codex" in existing_prev
                    or "claudetracing.codex" in existing_prev
                ):
                    new_items[idx + 1] = prev_json
                elif strict_custom:
                    raise ValueError(
                        f"{config_path} already has a custom `--previous-notify` entry ({existing_prev!r})."
                    )
                else:
                    return
            else:
                new_items.append(prev_json)
        else:
            new_items.extend(["--previous-notify", prev_json])
        doc["notify"] = new_items
        rendered = tomlkit.dumps(doc)
        tomlkit.parse(rendered)
        config_path.write_text(rendered, encoding="utf-8")
        return

    if existing_notify is not None and not _is_owned_notify(existing_notify):
        if strict_custom:
            raise ValueError(
                f"{config_path} already has a custom `notify` entry ({existing_notify!r}). "
                f'Update it manually to: notify = ["mlflow-codex", "notify-hook"]'
            )
        return

    if "notify" in doc:
        doc["notify"] = target_cmd
        rendered = tomlkit.dumps(doc)
    else:
        header_doc = tomlkit.document()
        header_doc.add(
            tomlkit.comment(
                "Added by claudetracing — forwards each Codex turn to MLflow Tracing."
            )
        )
        header_doc.add("notify", target_cmd)
        prefix = tomlkit.dumps(header_doc)
        rendered = f"{prefix}\n{original}" if original.strip() else prefix

    tomlkit.parse(rendered)
    config_path.write_text(rendered, encoding="utf-8")


def configure_codex(
    project_root: Path,
    tracking_uri: str,
    experiment_id: str = "0",
    trace_location: str | None = None,
    *,
    tracking_token: str | None = None,
    project_local: bool = True,
) -> tuple[Path, Path]:
    """Configure Codex CLI tracing in `.codex/config.toml` and `.codex/mlflow-tracing.json`.

    Follows `@mlflow/codex` conventions:
      - Sets `notify = ["mlflow-codex", "notify-hook"]` in `.codex/config.toml` (and
        syncs `$CODEX_HOME/config.toml` so `codex` CLI invokes the hook) while
        preserving comments and existing TOML sections.
      - Refuses to overwrite an unrelated user `notify` command.
      - Writes `trackingUri` and `experimentId` to `.codex/mlflow-tracing.json`.

    Returns:
        Tuple of `(config_toml_path, mlflow_tracing_json_path)`.
    """
    codex_dir = resolve_codex_dir(project_root, project_local=project_local)
    codex_dir.mkdir(parents=True, exist_ok=True)

    config_path = codex_dir / CONFIG_TOML_FILENAME
    tracing_path = codex_dir / TRACING_CONFIG_FILENAME

    _write_notify_to_toml(config_path, strict_custom=True)

    # Also ensure $CODEX_HOME/config.toml has the notify hook if CODEX_HOME exists or is set.
    # Use the claudetracing.codex notify-hook shim in $CODEX_HOME so DATABRICKS_CONFIG_PROFILE
    # and MLFLOW_TRACKING_TOKEN are injected before delegating to `mlflow-codex notify-hook`.
    home_dir = codex_home()
    if project_local and (os.environ.get("CODEX_HOME") or home_dir.exists()):
        home_cfg = home_dir / CONFIG_TOML_FILENAME
        if home_cfg.resolve() != config_path.resolve():
            shim_cmd = [sys.executable, "-m", "claudetracing.codex", "notify-hook"]
            _write_notify_to_toml(home_cfg, strict_custom=False, notify_cmd=shim_cmd)

    tracing_cfg = CodexTracingConfig(
        tracking_uri=tracking_uri,
        experiment_id=str(experiment_id),
        trace_location=trace_location,
        tracking_token=tracking_token,
    )
    tracing_path.write_text(
        json.dumps(
            tracing_cfg.model_dump(by_alias=True, exclude_none=True),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return config_path, tracing_path


def load_codex_tracing_config(
    project_root: Path | None = None,
) -> tuple[CodexTracingConfig | None, str, Path | None]:
    """Load Codex tracing config following @mlflow/codex precedence:
    project-local (./.codex/mlflow-tracing.json) > user (~/.codex/mlflow-tracing.json).
    """
    root = (project_root or Path.cwd()).resolve()
    candidates = [
        ("project", root / ".codex" / TRACING_CONFIG_FILENAME),
        ("user", codex_home() / TRACING_CONFIG_FILENAME),
    ]
    for scope, path in candidates:
        if path.exists():
            try:
                cfg = CodexTracingConfig.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
                return cfg, scope, path
            except Exception:
                continue
    return None, "none", None


def get_codex_status(project_root: Path | None = None) -> CodexStatus:
    """Return the current Codex tracing configuration status."""
    cfg, scope, tracing_path = load_codex_tracing_config(project_root)
    binary_ok = is_mlflow_codex_installed()
    if cfg is None or tracing_path is None:
        return CodexStatus(enabled=False, binary_installed=binary_ok)

    config_toml = tracing_path.parent / CONFIG_TOML_FILENAME
    has_hook = False
    if config_toml.exists():
        try:
            doc = tomlkit.parse(config_toml.read_text(encoding="utf-8"))
            has_hook = _is_owned_notify(doc.get("notify"))
        except Exception:
            has_hook = False

    return CodexStatus(
        enabled=bool(cfg.tracking_uri and has_hook),
        tracking_uri=cfg.tracking_uri,
        experiment_id=cfg.experiment_id,
        trace_location=cfg.trace_location,
        scope=scope,
        config_path=tracing_path,
        binary_installed=binary_ok,
    )


def _remove_notify_from_toml(config_path: Path) -> bool:
    """Remove owned notify hook (or unchain from SkyComputerUseClient) in a TOML file."""
    if not config_path.exists():
        return False
    try:
        doc = tomlkit.parse(config_path.read_text(encoding="utf-8"))
        existing = doc.get("notify")
        if _is_sky_computer_use_notify(existing) and _is_owned_notify(existing):
            items = [str(x) for x in existing]  # type: ignore[union-attr]
            if "--previous-notify" in items:
                idx = items.index("--previous-notify")
                del items[idx : idx + 2]
                doc["notify"] = items
                config_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
                return True
            return False
        if _is_owned_notify(existing):
            del doc["notify"]
            rendered = tomlkit.dumps(doc).strip()
            if rendered:
                config_path.write_text(rendered + "\n", encoding="utf-8")
            else:
                config_path.unlink()
            return True
    except Exception:
        pass
    return False


def disable_codex(
    project_root: Path | None = None, *, project_local: bool = True
) -> bool:
    """Remove MLflow Codex tracing configuration from .codex/."""
    codex_dir = resolve_codex_dir(project_root, project_local=project_local)
    config_path = codex_dir / CONFIG_TOML_FILENAME
    tracing_path = codex_dir / TRACING_CONFIG_FILENAME

    changed = False
    if tracing_path.exists():
        tracing_path.unlink()
        changed = True

    if _remove_notify_from_toml(config_path):
        changed = True

    return changed


def run_codex_hook(payload: str, project_root: Path | None = None) -> int:
    """Populate tracing environment variables and delegate to `mlflow-codex notify-hook`."""
    from claudetracing.setup import load_tracing_env

    if not payload or not payload.strip():
        return 0

    cwd = project_root
    if cwd is None:
        try:
            data = json.loads(payload)
            if isinstance(data, dict) and data.get("cwd"):
                cwd = Path(str(data["cwd"]))
        except Exception:
            pass

    root = (cwd or Path.cwd()).resolve()
    load_tracing_env(root)

    binary = shutil.which("mlflow-codex")
    if not binary:
        return 0

    proc = subprocess.run(
        [binary, "notify-hook", payload],
        cwd=root,
        env=os.environ.copy(),
    )
    return proc.returncode


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "notify-hook":
        args = args[1:]
    payload_arg = args[0] if args else ""
    raise SystemExit(run_codex_hook(payload_arg))
