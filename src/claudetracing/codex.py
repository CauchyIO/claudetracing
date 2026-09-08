"""Codex notify setup and durable, project-scoped MLflow export workers."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback
from typing import Literal
from uuid import UUID

from filelock import FileLock
from pydantic import BaseModel, Field
import tomlkit


class Notification(BaseModel):
    type: Literal["agent-turn-complete"]
    thread_id: UUID = Field(alias="thread-id")
    cwd: Path


class Target(BaseModel):
    tracking_uri: str
    experiment: str
    archive: bool = True


class Registry(BaseModel):
    projects: dict[str, Target] = Field(default_factory=dict)
    previous_notify: list[str] = Field(default_factory=list)


class State(BaseModel):
    traces: dict[str, str] = Field(default_factory=dict)
    run_id: str | None = None


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).resolve()


def write_json(path: Path, data: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(data.model_dump_json(indent=2))
    temporary.chmod(0o600)
    temporary.replace(path)


def registry() -> Registry:
    path = codex_home() / "claudetracing.json"
    return (
        Registry.model_validate_json(path.read_text()) if path.exists() else Registry()
    )


def configure(
    project: Path, tracking_uri: str, experiment: str, archive: bool = True
) -> Path:
    """Register a project and preserve the existing user-level TOML notifier."""
    home = codex_home()
    home.mkdir(parents=True, exist_ok=True)
    with FileLock(str(home / "claudetracing-setup.lock")):
        config_path = home / "config.toml"
        original = config_path.read_text() if config_path.exists() else ""
        config = tomlkit.parse(original)
        previous = config.get("notify", [])
        if not isinstance(previous, list) or not all(
            isinstance(arg, str) for arg in previous
        ):
            raise ValueError("Codex notify must be an array of strings")
        data = registry()
        owned = len(previous) >= 4 and previous[1:4] == [
            "-m",
            "claudetracing.codex",
            "notify",
        ]
        if not owned:
            data.previous_notify = list(previous)
        data.projects[str(project.resolve())] = Target(
            tracking_uri=tracking_uri, experiment=experiment, archive=archive
        )
        config["notify"] = [sys.executable, "-m", "claudetracing.codex", "notify"]
        rendered = tomlkit.dumps(config)
        # Parse before writing; backup is never overwritten by a subsequent init.
        tomlkit.parse(rendered)
        backup = home / "config.before-claudetracing.toml"
        if original and not backup.exists():
            backup.write_text(original)
            backup.chmod(0o600)
        write_json(home / "claudetracing.json", data)
        temporary = config_path.with_suffix(".tmp")
        temporary.write_text(rendered)
        temporary.chmod(0o600)
        temporary.replace(config_path)
    return config_path


def target_for(cwd: Path) -> tuple[Path, Target] | None:
    matches = [
        (Path(root), target)
        for root, target in registry().projects.items()
        if cwd.resolve().is_relative_to(Path(root))
    ]
    return max(matches, key=lambda match: len(match[0].parts)) if matches else None


def export_session(notification: Notification) -> None:
    """Backfill completed turns and archive a consistent snapshot under a session lock."""
    match = target_for(notification.cwd)
    if match is None:
        return
    project, target = match
    session = str(notification.thread_id)
    uri = os.environ.get("MLFLOW_TRACKING_URI", target.tracking_uri)
    experiment_name = os.environ.get("MLFLOW_EXPERIMENT_NAME", target.experiment)
    experiment_override = os.environ.get("MLFLOW_EXPERIMENT_ID")
    key = hashlib.sha256(
        json.dumps([str(project), uri, experiment_name, experiment_override]).encode()
    ).hexdigest()[:20]
    directory = codex_home() / "claudetracing" / key
    directory.mkdir(parents=True, exist_ok=True)
    with FileLock(str(directory / f"{session}.lock")):
        paths = list((codex_home() / "sessions").rglob(f"*{session}.jsonl"))
        if len(paths) != 1:
            raise FileNotFoundError(
                f"Expected one Codex rollout for {session}, found {len(paths)}"
            )
        snapshot = paths[0].read_bytes()
        from claudetracing.codex_transcript import completed_turns, emit_turn

        records, turns = completed_turns(snapshot)
        metadata = next((r.payload for r in records if r.type == "session_meta"), {})
        if metadata.get("id") != session or not Path(
            metadata.get("cwd", "")
        ).resolve().is_relative_to(project):
            raise ValueError(
                "Codex transcript session/cwd does not match the configured project"
            )
        # Pin configuration before MLflow imports initialize any Databricks clients.
        os.environ["MLFLOW_TRACKING_URI"] = uri
        import mlflow
        from mlflow import MlflowClient

        mlflow.set_tracking_uri(uri)
        client = MlflowClient(tracking_uri=uri)
        if experiment_override:
            experiment = client.get_experiment(experiment_override)
        else:
            experiment = client.get_experiment_by_name(experiment_name)
            if experiment is None:
                experiment = client.get_experiment(
                    client.create_experiment(
                        experiment_name,
                        artifact_location=(directory / "artifacts").as_uri()
                        if uri.startswith("sqlite:")
                        else None,
                    )
                )
        state_path = directory / f"{session}.json"
        state = (
            State.model_validate_json(state_path.read_text())
            if state_path.exists()
            else State()
        )
        for turn in turns:
            if turn.id not in state.traces:
                state.traces[turn.id] = emit_turn(
                    client, experiment.experiment_id, session, turn
                )
                write_json(state_path, state)
        if target.archive:
            if state.run_id is None:
                run = client.create_run(
                    experiment.experiment_id,
                    tags={
                        "mlflow.runName": f"Codex conversation {session}",
                        "codex.session_id": session,
                    },
                )
                state.run_id = run.info.run_id
                write_json(state_path, state)
            with tempfile.TemporaryDirectory() as temporary:
                archive = Path(temporary) / "rollout.jsonl"
                archive.write_bytes(snapshot)
                client.log_artifact(
                    state.run_id, str(archive), artifact_path="conversation"
                )
            client.set_tag(
                state.run_id,
                "codex.rollout_sha256",
                hashlib.sha256(snapshot).hexdigest(),
            )
            client.set_terminated(state.run_id)


def notify(raw: str) -> None:
    """Forward the original notification and detach export so CLI exit cannot kill it."""
    directory = codex_home() / "claudetracing"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "notify.log").open("a") as log:
        previous = registry().previous_notify
        if previous:
            subprocess.Popen(
                [*previous, raw],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
                close_fds=True,
            )
        payload = json.loads(raw)
        if payload.get("type") != "agent-turn-complete":
            return
        notification = Notification.model_validate(payload)
        if target_for(notification.cwd) is None:
            return
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".pending.json", dir=directory, delete=False
        ) as pending:
            pending.write(notification.model_dump_json(by_alias=True))
        subprocess.Popen(
            [sys.executable, "-m", "claudetracing.codex", "worker", pending.name],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
            close_fds=True,
        )


def main() -> None:
    os.umask(0o077)
    try:
        command, argument = sys.argv[1:]
        if command == "notify":
            notify(argument)
        elif command == "worker":
            path = Path(argument)
            export_session(Notification.model_validate_json(path.read_text()))
            path.unlink()
        else:
            raise ValueError(f"Unknown Codex hook command: {command}")
    except Exception:
        # Hook exceptions are otherwise invisible in Codex. Keep full diagnostics locally.
        directory = codex_home() / "claudetracing"
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "errors.log").open("a") as log:
            traceback.print_exc(file=log)
        raise


if __name__ == "__main__":
    main()
