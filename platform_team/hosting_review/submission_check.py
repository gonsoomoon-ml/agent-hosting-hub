"""Unpack a team's submission and check its layout. Both CodeBuild steps of the hosting review use it.

    python -m platform_team.hosting_review.submission_check <zip> <dest>

unpacks <zip> into <dest>, prints each problem it finds and exits with 1 when there is one.
A submission is the agent's code and its requirements.txt: main.py and requirements.txt at the top of the zip.
requirements.txt may name packages on the package index only (a name, extras, versions; no marker). The scan
audits those lines and the deploy installs those lines, so the rule (parse_requirements) is the same for both.
"""
import re
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

REQUIRED_FILES = ("main.py", "requirements.txt")
_PIP_OPTION = re.compile(r"(^|\s)--?[A-Za-z]")                       # -r, -e, --index-url, --hash=...
_DIRECT_REFERENCE = re.compile(r"@|://|(^|\s)file:")                  # pkg @ url, a URL, file:...
_BY_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"   # name
                      r"\s*(?:\[[A-Za-z0-9._,\s-]*\])?"               # [extras]
                      r"[\s<>=!~,.*+A-Za-z0-9()-]*")                  # versions
# An environment marker (; ...) is refused: the scan's pip tests it against the scan machine and the deploy's uv
# against the Runtime target, so a marked line could be skipped by the audit and installed by the deploy.
RUNTIME_TARGET = "Linux aarch64, CPython 3.13"


def _unsafe(info: zipfile.ZipInfo) -> bool:
    """A name that is absolute (also C:\\ or \\\\server), climbs out of the folder (..), or is a symbolic link."""
    path = PurePosixPath(info.filename.replace("\\", "/"))
    return (path.is_absolute() or bool(PureWindowsPath(info.filename).anchor) or ".." in path.parts
            or stat.S_ISLNK(info.external_attr >> 16))


def unpack(zip_path: Path, dest: Path) -> None:
    """Unpack the submission into dest. Every name is checked before anything is written."""
    with zipfile.ZipFile(zip_path) as z:
        infos = z.infolist()
        for info in infos:
            if _unsafe(info):
                raise ValueError(f"unsafe path in the submission: {info.filename}")
        Path(dest).mkdir(parents=True, exist_ok=True)
        z.extractall(dest)


def check_layout(src: Path) -> list[str]:
    """The problems with the unpacked submission's layout. An empty list means it passes."""
    return [f"missing: {name}" for name in REQUIRED_FILES if not (Path(src) / name).is_file()]


def parse_requirements(text: str) -> tuple[list[str], list[str]]:
    """The requirement lines of a requirements.txt, and the problems with it. Comments and blank lines are
    dropped and `\\` continuations joined. A line that picks its own source is a problem: a pip option (it can
    change the index or pull in another file) or a direct reference (a URL or file the audit cannot check).
    So is an environment marker: the audit and the deploy would each decide for their own machine."""
    deps, problems = [], []
    for raw in text.replace("\\\n", " ").splitlines():
        line = re.sub(r"(^|\s)#.*$", "", raw).strip()
        if not line:
            continue
        if _PIP_OPTION.search(line):
            problems.append(f"requirements.txt: pip options are not allowed: {raw.strip()}")
        elif _DIRECT_REFERENCE.search(line):
            problems.append(f"requirements.txt: direct references are not allowed (name a package on the index): {raw.strip()}")
        elif ";" in line:
            problems.append(f"requirements.txt: environment markers are not allowed (the Runtime is {RUNTIME_TARGET}): "
                            f"{raw.strip()}")
        elif not _BY_NAME.fullmatch(line):
            problems.append(f"requirements.txt: not a package name with an optional version: {raw.strip()}")
        else:
            deps.append(" ".join(line.split()))
    return deps, problems


def check_requirements(src: Path) -> list[str]:
    """The problems with the submission's requirements.txt (none when it is missing: check_layout says so)."""
    path = Path(src) / "requirements.txt"
    if not path.is_file():
        return []
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return ["requirements.txt: not UTF-8 text"]
    return parse_requirements(text)[1]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m platform_team.hosting_review.submission_check <zip> <dest>")
        return 2
    zip_path, dest = Path(argv[0]), Path(argv[1])
    try:
        unpack(zip_path, dest)
    except (ValueError, zipfile.BadZipFile) as e:
        print(f"submission refused: {e}")
        return 1
    problems = check_layout(dest) + check_requirements(dest)
    for problem in problems:
        print(f"submission refused: {problem}")
    if problems:
        return 1
    print(f"submission unpacked into {dest}: {', '.join(REQUIRED_FILES)} present")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
