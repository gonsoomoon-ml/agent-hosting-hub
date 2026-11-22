"""Unpack a team's submission and check its layout. Both CodeBuild steps of the hosting review use it.

    python -m platform_team.hosting_review.submission_check <zip> <dest>

unpacks <zip> into <dest>, prints each problem it finds and exits with 1 when there is one.
A submission is the agent's code and its requirements.txt: main.py and requirements.txt at the top of the zip.
"""
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

REQUIRED_FILES = ("main.py", "requirements.txt")


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
    problems = check_layout(dest)
    for problem in problems:
        print(f"submission refused: {problem}")
    if problems:
        return 1
    print(f"submission unpacked into {dest}: {', '.join(REQUIRED_FILES)} present")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
