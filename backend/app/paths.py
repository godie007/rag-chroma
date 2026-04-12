from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def default_eval_jsonl_path() -> Path:
    return project_root() / "evals" / "sample_eval.jsonl"


def resolve_eval_jsonl_path(relative: str | None) -> Path:
    root = project_root()
    evals_dir = (root / "evals").resolve()
    if not relative or not relative.strip():
        return default_eval_jsonl_path()
    rel = relative.strip().replace("\\", "/").lstrip("/")
    if ".." in Path(rel).parts:
        raise ValueError("Ruta de evaluación no permitida")
    path = (root / rel).resolve()
    try:
        path.relative_to(evals_dir)
    except ValueError as e:
        raise ValueError(
            "Solo se permiten archivos dentro de la carpeta evals/ del proyecto"
        ) from e
    return path
