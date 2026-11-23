#!/usr/bin/env python3
"""The demo video in one file: per clip its raw take, speed, window and beats (the captions); the cards; the six reels.

  python3 demo_video/scripts/build.py --check [--lang ko]    write the plugin's script files and check every text
  python3 demo_video/scripts/build.py [--lang ko]            the same, then cut the clips, the cards and the reels

Every caption and card text lives here under a language key. Before anything is written, each text is checked against
the video plugin's rules for captions (references/script.md of the plugin):
  - at most 45 characters; no em dash, middle dot or arrow (U+2014, U+00B7, U+2192); no speed label and no note about
    the recording;
  - a caption, a chapter's title and a card's row is one sentence in the 합니다 style (it ends in 니다);
  - a stage carries no more captions than its budget (BUDGET);
  - a reel names only clips and cards defined here.
A text that breaks a rule stops the build (exit 2) with one line per text. Without --check the build then runs the
plugin's edit_demo.py (clip, reel) and make_cards.py, found through DEMO_VIDEO_PLUGIN (the plugin's scripts folder),
with the Python that runs this file (make_cards.py needs Pillow). Everything is written under demo_video/out/
(git-ignored): scripts/<lang>/, clips/<lang>/, cards/<lang>/, reels/ (the manifests next to the reels).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "demo_video" / "out"
PLUGIN_URL = "https://github.com/gonsoomoon-ml/claude-extensions/tree/main/plugins/demo-video"

LIMIT = 45
BANNED = {"—": "an em dash", "·": "a middle dot", "→": "an arrow"}
SPEED = re.compile(r"\d+(\.\d+)?\s*(배속|배\b|[x×]\b)|배속|빨리 감기|느리게 재생")
RECORDING = re.compile(r"녹화|촬영|재생 속도|이 영상에서는")
STAGES = {0: "준비", 1: "1단계", 2: "2단계", 3: "3단계", 4: "4단계", 5: "5단계"}
BUDGET = {0: 5, 1: 11, 2: 12, 3: 8, 4: 10, 5: 18}     # captions per stage, all clips of the stage together
DEFAULT_SPEED = 1.25                                    # interactions; a wait gets its own clip at 4


def clip(raw: str, speed: float = DEFAULT_SPEED, start: float | None = None, end: float | None = None) -> dict:
    """A clip: a window of one raw take (demo_video/out/raw/<raw>.webm) at one speed, and its beats per language.
    A beat is {"at": <camlog anchor or raw seconds>, "text": ..., optional "offset", "dur", "pos"} (edit_demo.py)."""
    return {"raw": raw, "speed": speed, "start": start, "end": end, "beats": {"ko": []}}


SPEC = {
    # one clip per take for now; a take with a wait is split into clips at 1.25 and at 4 when its beats are written
    "clips": {
        "00-home": clip("00-home"),
        "11-find": clip("11-find"),
        "12-make": clip("11-find"),      # the second part of the 11-find recording, from its note make_asked
        "13-submit": clip("13-submit"),
        "21-review": clip("21-review"),
        "22-works": clip("22-works"),
        "23-reject": clip("23-reject"),
        "24-again": clip("24-again"),
        "25-approved": clip("25-approved"),
        "26-answers": clip("26-answers"),
        "31-logonly": clip("31-logonly"),
        "32-passes": clip("32-passes"),
        "33-record": clip("33-record"),
        "41-enforce": clip("41-enforce"),
        "42-blocked": clip("42-blocked"),
        "43-before": clip("43-before"),
        "44-attach": clip("44-attach"),
        "45-after": clip("45-after"),
        "51-usage": clip("51-usage"),
        "52-incident": clip("52-incident"),
        "53-alarm": clip("53-alarm"),
        "54-stop": clip("54-stop"),
        "55-neighbours": clip("55-neighbours"),
        "56-cause": clip("56-cause"),
        "57-back": clip("57-back"),
    },
    # a card: kicker, title, and either rows (sentences; "accent" = the index of the accented row) or, for a chapter
    # card, "where" (the place the chapter happens, a name rather than a sentence)
    "cards": {
        "ko": {
            "card-intro": {"seconds": 4, "kicker": "AI 에이전트 호스팅 허브 on Amazon Bedrock AgentCore",
                           "title": "팀은 스스로 올리고, 플랫폼팀은 한 곳에서 관리합니다", "rows": []},
            "card-ch0": {"seconds": 3, "kicker": "준비", "title": "플랫폼팀이 허브를 한 번 만들어 둡니다",
                         "where": "허브 화면의 홈"},
            "card-ch1": {"seconds": 3, "kicker": "1단계. 호스팅 신청", "title": "팀은 플랫폼팀 없이 찾고, 만들고, 신청합니다",
                         "where": "Claude Code와 AWS Agent Registry"},
            "card-ch2": {"seconds": 3, "kicker": "2단계. 호스팅 심사", "title": "신청이 들어오면 허브가 자동으로 심사합니다",
                         "where": "심사 파이프라인과 AgentCore Runtime"},
            "card-ch3": {"seconds": 3, "kicker": "3단계. 전사 정책 시험", "title": "새 전사 정책을 막지 않고 먼저 시험합니다",
                         "where": "Policy in AgentCore의 기록 모드"},
            "card-ch4": {"seconds": 3, "kicker": "4단계. 전사 정책 적용", "title": "전사 정책 하나가 모든 에이전트에 걸립니다",
                         "where": "AgentCore Gateway와 커스텀 가드레일"},
            "card-ch5": {"seconds": 3, "kicker": "5단계. 이상 대응", "title": "문제를 일으킨 에이전트 하나만 멈춥니다",
                         "where": "CloudWatch 알람과 AgentCore Runtime"},
            "card-compare": {"seconds": 8, "kicker": "가드레일 두 가지", "title": "기본 제공 가드레일과 커스텀 가드레일",
                             "rows": ["기본 제공은 설정으로 걸고 기록 모드로 먼저 시험합니다",
                                      "커스텀은 사내 코드로 막고 민감 정보를 가립니다",
                                      "둘 다 게이트웨이에 걸려 모든 에이전트에 적용됩니다"], "accent": 2},
            "card-summary": {"seconds": 9, "kicker": "정리", "title": "팀은 스스로 올리고, 플랫폼팀은 한 곳에서 관리합니다",
                             "rows": ["팀은 카탈로그에서 찾고 템플릿으로 만들어 스스로 신청합니다",
                                      "허브가 자동으로 심사하고 통과한 것만 올립니다",
                                      "전사 정책은 게이트웨이에 한 번 걸면 모두에 적용됩니다",
                                      "이상 에이전트 하나만 멈추고 이웃은 계속 답합니다"], "accent": 3},
            "card-closing": {"seconds": 7, "kicker": "누가 무엇을 맡나", "title": "AgentCore가 주는 것과 플랫폼팀이 만드는 것",
                             "rows": ["AgentCore는 Runtime, Gateway, Policy를 줍니다",
                                      "AgentCore는 Registry와 관측도 줍니다",
                                      "플랫폼팀은 심사 파이프라인과 운영 명령, 허브 화면을 만듭니다"]},
        },
    },
    # a segment is a clip's or a card's name, or {"name": ..., "start", "end", "fade_in", "fade_out"} (seconds of
    # the finished clip; 0 = a hard cut, for the pieces of one scene cut at different speeds)
    "reels": {
        "main": ["card-intro",
                 "card-ch0", "00-home",
                 "card-ch1", "11-find", "12-make", "13-submit",
                 "card-ch2", "21-review", "22-works", "23-reject", "24-again", "25-approved", "26-answers",
                 "card-ch3", "31-logonly", "32-passes", "33-record",
                 "card-ch4", "41-enforce", "42-blocked", "43-before", "44-attach", "45-after", "card-compare",
                 "card-ch5", "51-usage", "52-incident", "53-alarm", "54-stop", "55-neighbours", "56-cause", "57-back",
                 "card-summary", "card-closing"],
        "stage-1": ["card-ch1", "11-find", "12-make", "13-submit"],
        "stage-2": ["card-ch2", "21-review", "22-works", "23-reject", "24-again", "25-approved", "26-answers"],
        "stage-3": ["card-ch3", "31-logonly", "32-passes", "33-record"],
        "stage-4": ["card-ch4", "41-enforce", "42-blocked", "43-before", "44-attach", "45-after", "card-compare"],
        "stage-5": ["card-ch5", "51-usage", "52-incident", "53-alarm", "54-stop", "55-neighbours", "56-cause",
                    "57-back"],
    },
}


# ---------------------------------------------------------------------------------------------------- the rules

def stage(c: dict) -> int:
    """The stage of a clip: the first digit of its raw take's name (00-home is 준비, 21-review is stage 2)."""
    return int(c["raw"][0])


def segment_name(seg) -> str:
    return seg if isinstance(seg, str) else seg["name"]


def text_problems(text: str, sentence: bool) -> list[str]:
    """What is wrong with one text: every text keeps the length, character and wording rules; a sentence is also one
    sentence in the 합니다 style."""
    found = []
    if len(text) > LIMIT:
        found.append(f"{len(text)} characters, more than {LIMIT}")
    found += [f"holds {what}" for ch, what in BANNED.items() if ch in text]
    if SPEED.search(text):
        found.append("names a speed")
    if RECORDING.search(text):
        found.append("talks about the recording")
    if sentence:
        body = text.rstrip(".")
        if not body.endswith("니다"):
            found.append("is not one sentence in the 합니다 style (it must end in 니다)")
        elif re.search(r"[.?!](\s|$)", body):
            found.append("is more than one sentence")
    return found


def card_texts(card: dict) -> list[str]:
    """A card's texts in the order they show: kicker, title, then the rows or the chapter's place."""
    return [card["kicker"], card["title"], *card.get("rows", []), *([card["where"]] if "where" in card else [])]


def problems(spec: dict, lang: str) -> list[str]:
    found = []
    if lang not in spec["cards"]:
        return [f"no texts in the language {lang!r} (there are: {', '.join(sorted(spec['cards']))})"]
    cards = spec["cards"][lang]
    for name, card in cards.items():
        checks = [(card["kicker"], False), (card["title"], "where" in card), *((r, True) for r in card.get("rows", [])),
                  *([(card["where"], False)] if "where" in card else [])]
        for text, sentence in checks:
            found += [f"{name}: {text!r} {p}" for p in text_problems(text, sentence)]
    per_stage = dict.fromkeys(BUDGET, 0)
    for name, c in spec["clips"].items():
        beats = c["beats"].get(lang, [])
        per_stage[stage(c)] += len(beats)
        for b in beats:
            found += [f"{name}: {b['text']!r} {p}" for p in text_problems(b["text"], True)]
    for s, n in per_stage.items():
        if n > BUDGET[s]:
            found.append(f"{STAGES[s]}: {n} captions, more than its budget of {BUDGET[s]}")
    known = set(spec["clips"]) | set(cards)
    for reel, segments in spec["reels"].items():
        found += [f"reel {reel}: {segment_name(s)!r} is neither a clip nor a card of this file" for s in segments
                  if segment_name(s) not in known]
    return found


# ---------------------------------------------------------------------------------------- the plugin's script files

def clip_script(c: dict, lang: str) -> dict:
    """edit_demo.py's script for a clip: no title (the chapter cards carry it), the window, the speed, the beats."""
    return {"start": c["start"], "end": c["end"], "speed": c["speed"], "beats": c["beats"].get(lang, [])}


def card_lines(card: dict) -> list[list]:
    lines = [["kicker", card["kicker"]], ["title", card["title"]]]
    if "where" in card:
        return lines + [["gap"], ["row", card["where"], "dim"]]
    rows = card.get("rows", [])
    if rows:
        lines.append(["gap"])
    for i, row in enumerate(rows):
        lines.append(["row", row, "accent"] if card.get("accent") == i else ["row", row])
    return lines


def reel_manifest(spec: dict, reel: str, lang: str) -> dict:
    segments = []
    for seg in spec["reels"][reel]:
        name = segment_name(seg)
        folder = "clips" if name in spec["clips"] else "cards"
        entry = {"file": f"{folder}/{lang}/{name}.mp4"}
        if not isinstance(seg, str):
            entry |= {k: v for k, v in seg.items() if k != "name"}
        segments.append(entry)
    return {"fade": 0.4, "segments": segments}


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def reel_file(reel: str, lang: str) -> str:
    return f"hosting-hub-{reel}-{lang}"


def clip_command(plugin: Path, name: str, c: dict, lang: str, out: Path) -> list[str]:
    """edit_demo.py clip for one clip. A clip with no beats is cut without captions: the plugin would otherwise burn
    the camera's shot labels, which are notes for the person who records."""
    cmd = [sys.executable, str(plugin / "edit_demo.py"), "clip", str(out / "raw" / f"{c['raw']}.webm"),
           "--script", str(out / "scripts" / lang / f"{name}.json"), "--out", str(out / "clips" / lang / f"{name}.mp4")]
    return cmd + ([] if c["beats"].get(lang) else ["--no-captions"])


# ---------------------------------------------------------------------------------------------------------- run

def run(spec: dict, lang: str = "ko", out: Path = OUT, check_only: bool = False) -> None:
    found = problems(spec, lang)
    if found:
        for line in found:
            print(line, file=sys.stderr)
        print(f"build stopped: {len(found)} text(s) break the rules; nothing was written", file=sys.stderr)
        raise SystemExit(2)
    for name, c in spec["clips"].items():
        write(out / "scripts" / lang / f"{name}.json", clip_script(c, lang))
    write(out / "cards" / lang / "cards.json", {n: {"seconds": card["seconds"], "lines": card_lines(card)}
                                                for n, card in spec["cards"][lang].items()})
    for reel in spec["reels"]:
        write(out / "reels" / f"{reel_file(reel, lang)}.json", reel_manifest(spec, reel, lang))
    beats = sum(len(c["beats"].get(lang, [])) for c in spec["clips"].values())
    print(f"checked: {len(spec['cards'][lang])} cards, {len(spec['clips'])} clips with {beats} captions, "
          f"{len(spec['reels'])} reels; script files in {out}")
    if check_only:
        return
    plugin = _plugin()
    used = {segment_name(s) for segs in spec["reels"].values() for s in segs} & set(spec["clips"])
    missing = sorted({f"raw/{spec['clips'][n]['raw']}.webm" for n in used
                      if not (out / "raw" / f"{spec['clips'][n]['raw']}.webm").exists()})
    if missing:
        print(f"no raw take for {', '.join(missing)} (under {out}): record it with demo_video/scenes/record.sh",
              file=sys.stderr)
        raise SystemExit(1)
    for name in sorted(used):
        subprocess.run(clip_command(plugin, name, spec["clips"][name], lang, out), check=True)
    subprocess.run([sys.executable, str(plugin / "make_cards.py"), str(out / "cards" / lang / "cards.json"),
                    "--out", str(out / "cards" / lang)], check=True)
    for reel in spec["reels"]:
        subprocess.run([sys.executable, str(plugin / "edit_demo.py"), "reel", str(out / "reels" / f"{reel_file(reel, lang)}.json"),
                        "--out", str(out / "reels" / f"{reel_file(reel, lang)}.mp4")], check=True, cwd=out)


def _plugin() -> Path:
    import os
    folder = os.environ.get("DEMO_VIDEO_PLUGIN")
    if not folder or not (Path(folder) / "edit_demo.py").is_file() or not (Path(folder) / "make_cards.py").is_file():
        print("DEMO_VIDEO_PLUGIN must name the scripts folder of the demo-video plugin (edit_demo.py, make_cards.py): "
              f"{PLUGIN_URL}", file=sys.stderr)
        raise SystemExit(2)
    return Path(folder)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="write the script files and check every text; cut nothing")
    ap.add_argument("--lang", default="ko")
    ap.add_argument("--out", type=Path, default=OUT, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    run(SPEC, lang=a.lang, out=a.out.resolve(), check_only=a.check)


if __name__ == "__main__":
    main()
