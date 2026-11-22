"""Build the hub's code package for Lambda and CodeBuild, and the tool schemas Terraform reads.

    python -m platform_team.shared_code.code_package        # writes build/platform_team.zip and build/tool_schemas.json

The zip holds the platform_team package (.py files and the Cedar templates) and the boto3 installed in this
environment, copied file by file, so AWS runs the same boto3 version as the tests. Only the API models of the
services the hub's clients use are kept. The zip is byte-for-byte the same for the same input, so Terraform
sees no change when nothing changed.
"""
import json
import sys
import zipfile
from importlib import metadata
from pathlib import Path

import platform_team
from platform_team.sample_tools.tool_schema import SHARED_READ, TARGETS
from platform_team.shared_code.aws_helpers import _SERVICES

PACKAGE = Path(platform_team.__file__).parent
CODE_SUFFIXES = {".py", ".cedar"}
# boto3 and everything it imports (pure Python, so the zip runs on any Lambda architecture).
BOTO3_DISTRIBUTIONS = ("boto3", "botocore", "s3transfer", "jmespath", "python-dateutil", "six", "urllib3")
KEEP_MODELS = set(_SERVICES.values())
_FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def _hub_files() -> dict[str, Path]:
    return {f"platform_team/{f.relative_to(PACKAGE).as_posix()}": f
            for f in PACKAGE.rglob("*")
            if f.is_file() and f.suffix in CODE_SUFFIXES and "__pycache__" not in f.parts}


def _keep(name: str) -> bool:
    parts = name.split("/")
    if parts[0].startswith("..") or "__pycache__" in parts or name.endswith(".pyc"):
        return False
    if parts[:2] == ["botocore", "data"] and len(parts) > 3:          # botocore/data/<service>/<version>/...
        return parts[2] in KEEP_MODELS
    return True


def _boto3_files() -> dict[str, Path]:
    out = {}
    for dist_name in BOTO3_DISTRIBUTIONS:
        dist = metadata.distribution(dist_name)
        for f in dist.files or []:
            name = f.as_posix()
            if _keep(name):
                out[name] = Path(dist.locate_file(f))
    return out


def _write_zip(path: Path, files: dict[str, Path]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=_FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, files[name].read_bytes())


def build(out: Path = Path("build")) -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    zip_path, schemas_path, shared_path = out / "platform_team.zip", out / "tool_schemas.json", out / "shared_read.json"
    _write_zip(zip_path, {**_boto3_files(), **_hub_files()})
    schemas_path.write_text(json.dumps(TARGETS, indent=2, sort_keys=True) + "\n")
    shared_path.write_text(json.dumps(SHARED_READ, indent=2) + "\n")
    return {"zip": str(zip_path), "tool_schemas": str(schemas_path), "shared_read": str(shared_path),
            "bytes": zip_path.stat().st_size}


if __name__ == "__main__":
    result = build(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("build"))
    print(f"{result['zip']} ({result['bytes'] / 1e6:.1f} MB), {result['tool_schemas']}, {result['shared_read']}")
