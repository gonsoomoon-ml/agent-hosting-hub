"""Unpack a team's submission and check its layout. Both CodeBuild steps of the hosting review use it.

    python -m platform_team.hosting_review.submission_check <zip> <dest> <audit_file>

unpacks <zip> into <dest>, prints each problem it finds and exits with 1 when there is one. When there is none, it
writes <audit_file>: the requirement lines of the submission's requirements.txt (requirements_from), which the scan
step audits. A submission is the agent's code and its requirements.txt: main.py and requirements.txt at the top of
the zip. requirements.txt may name packages on the package index only (a name, extras, versions; no marker). The
deploy build installs from a file that requirements_from writes too, so the scan audits exactly the lines the deploy
installs: neither reads the team's file as pip or uv would (comments, continuations).
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


def requirements_from(text: str) -> str:
    """The platform's requirements file: the requirement lines of a requirements.txt (parse_requirements), one per
    line, with comments, blank lines and continuations gone. A line it refuses raises ValueError. The scan audits
    this file and the deploy build installs from this file; neither reads the team's own."""
    deps, problems = parse_requirements(text)
    if problems:
        raise ValueError("; ".join(problems))
    return "".join(f"{d}\n" for d in deps)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: python -m platform_team.hosting_review.submission_check <zip> <dest> <audit_file>")
        return 2
    zip_path, dest, audit_file = (Path(a) for a in argv)
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
    lines = requirements_from((dest / "requirements.txt").read_text(encoding="utf-8"))
    audit_file.parent.mkdir(parents=True, exist_ok=True)
    audit_file.write_text(lines, encoding="utf-8")
    print(f"submission unpacked into {dest}: {', '.join(REQUIRED_FILES)} present; {len(lines.splitlines())} "
          f"requirement lines written to {audit_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
