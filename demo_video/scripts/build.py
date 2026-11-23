#!/usr/bin/env python3
"""The demo video in one file: per take its pieces (a window of a raw take at one speed, with its captions); the
cards; the six reels.

  python3 demo_video/scripts/build.py --check [--lang ko]    write the plugin's script files and check every text
  python3 demo_video/scripts/build.py [--lang ko]            the same, then cut the clips, the cards and the reels

Every caption and card text lives here under a language key. Before anything is written, each text is checked against
the video plugin's rules for captions (references/script.md of the plugin):
  - at most 45 characters; no em dash, middle dot or arrow (U+2014, U+00B7, U+2192); no speed label (a dimension such
    as "M4 x 12 mm" is not one) and no note about the recording;
  - a caption, a chapter's title and a card's row is one sentence in the 합니다 style (it ends in 니다);
  - a caption is anchored to a shot or a note of its take's camlog, never to raw seconds;
  - a stage carries no more captions than its budget (BUDGET);
  - a reel names only takes and cards defined here.
A text that breaks a rule stops the build (exit 2) with one line per text. Without --check the build then reads the
camlogs: a caption whose anchor the camlog does not hold, or that falls outside its piece (or less than ROOM seconds
of the finished piece before its end), stops the build the same way before anything is cut. Then it runs the plugin's
edit_demo.py (clip, reel) and make_cards.py, found through DEMO_VIDEO_PLUGIN (the plugin's scripts folder), with the
Python that runs this file (make_cards.py needs Pillow). In a reel the pieces of one take are joined with hard cuts;
the edges between takes and cards fade (0.4 s). Everything is written under demo_video/out/ (git-ignored):
scripts/<lang>/ and clips/<lang>/ (<take>.<n>, one per piece), cards/<lang>/, reels/ (the manifests next to the reels).
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
# a number with 배속, 배 or x/× is a speed label, except a dimension such as "M4 x 12 mm" (x followed by a number)
SPEED = re.compile(r"\d+(\.\d+)?\s*(배속|배\b|[x×](?!\s*\d))|배속|빨리 감기|느리게 재생")
RECORDING = re.compile(r"녹화|촬영|재생 속도|이 영상에서는")
STAGES = {0: "준비", 1: "1단계", 2: "2단계", 3: "3단계", 4: "4단계", 5: "5단계"}
BUDGET = {0: 5, 1: 11, 2: 12, 3: 8, 4: 10, 5: 18}     # captions per stage, all pieces of the stage's takes together
DEFAULT_SPEED = 1.25                                    # interactions
WAIT = 4                                                # a wait (a review, a job, the alarm, Claude Code at work)
ROOM = 2.0                                              # seconds of the finished piece a caption needs at least


def piece(raw: str, start: float, end: float, speed: float = DEFAULT_SPEED, ko: list | tuple = ()) -> dict:
    """A piece of a take: the window start..end (seconds of demo_video/out/raw/<raw>.webm, as its camlog counts them)
    at one speed, and its captions per language. A take is one or more pieces, joined in a reel with hard cuts."""
    return {"raw": raw, "start": start, "end": end, "speed": speed, "beats": {"ko": list(ko)}}


def beat(at: str, text: str, **opts) -> dict:
    """A caption (the plugin's beat): anchored to a camlog event, 'shot:<key>[#n]' or '<note kind>[#n]', plus an
    optional "offset" (seconds), "dur" (seconds of the finished piece) and "pos": "top" (edit_demo.py)."""
    return {"at": at, "text": text, **opts}


# Windows are camlog seconds; each comment names the camlog events a piece holds. A wait plays at WAIT; a long wait is
# cut to its start or its end (a hard cut inside the take), and so is a stretch of typing in a terminal.
SPEC = {
    "clips": {
        # 준비: the hub screen's home page
        "00-home": [piece("00-home", 3.5, 41.5, ko=[      # wide 3.9, counts 9.9, flow1 14.9, flow2 21.9, platform 28.9,
            beat("shot:wide", "허브 화면 한 곳에서 호스팅된 에이전트와 공유 도구를 봅니다"),              # catalog 35.9
            beat("shot:flow1", "흐름 1은 팀이 에이전트를 올리면 허브가 자동으로 심사하는 길입니다"),
            beat("shot:flow2", "흐름 2는 플랫폼팀이 게이트웨이에서 정책을 걸고 지켜보는 길입니다"),
            beat("shot:platform", "게이트웨이 둘과 정책 엔진, 카탈로그, 심사 상태 머신을 한 번 만듭니다"),
            beat("shot:catalog", "카탈로그에는 승인된 에이전트와 공유 도구가 올라 있습니다", pos="top")])],
        # 1단계: one Claude Code session (11-find, then 12-make from the note make_asked), then the developer's shell
        "11-find": [piece("11-find", 15.6, 35.0, ko=[     # find_asked 16.1, record 27.3 (zoomed on the answer)
            beat("find_asked", "개발자는 Claude Code에게 부품 규격을 읽는 사내 도구를 찾게 합니다"),
            beat("shot:record", "카탈로그의 MCP 서버에서 공유 도구의 이름과 설명, 입력을 찾아 줍니다")])],
        "12-make": [
            piece("11-find", 37.9, 47.0, ko=[             # make_asked 38.3, ask1 41.6 (questions 2 to 4 are left out)
                beat("make_asked", "이어서 표준 템플릿으로 그 도구를 쓰는 에이전트를 만들게 합니다", pos="top")]),
            piece("11-find", 71.0, 79.4, ko=[             # ask5 71.3: a long command with 43 hidden lines; No at 76
                beat("shot:ask5", "Claude Code는 셸 명령을 실행하기 전에 개발자에게 묻습니다", dur=4.4, pos="top")]),
            piece("11-find", 79.4, 107.0, WAIT, ko=[      # work5 79.6: the No and its sentence; then the files are written
                beat("shot:work5", "개발자는 No로 답하고 실행 없이 파일만 만들게 합니다")]),
            piece("11-find", 107.0, 115.0, ko=[           # made 107.4
                beat("shot:made", "Claude Code가 파일 다섯 개를 만들고 올리지는 않았습니다")])],
        "13-submit": [
            piece("13-submit", 10.2, 21.5, ko=[           # publish_release 10.9, release 17.3; the next command's typing
                beat("publish_release", "개발자는 publish 한 줄로 release_review의 호스팅을 신청합니다")]),  # is cut
            piece("13-submit", 23.8, 37.5, ko=[           # publish_quality 24.4, both 31.1
                beat("shot:both", "quality_agent의 v1-vulnerable 판도 승인 대기가 됩니다")])],
        # 2단계: the reviews on the hub screen, the user's shell, the reject, the second submission
        "21-review": [
            piece("21-review", 4.5, 11.5, ko=[            # list 4.9, cards 10.0
                beat("shot:list", "신청이 들어오자 두 에이전트의 호스팅 심사가 저절로 시작됩니다")]),
            piece("21-review", 30.0, 38.6, WAIT),         # Scan running; release_review's Scan passes at 33.1
            piece("21-review", 38.6, 60.0, ko=[           # quality_failed 39.1, quality 40.6, release_card 47.6, steps 54.1
                beat("shot:quality", "quality_agent의 심사는 의존성 검사 Scan에서 실패해 멈춥니다", dur=5.0),
                beat("shot:steps", "심사 단계마다 AWS Lambda나 AWS CodeBuild가 일을 맡습니다", pos="top")]),
            piece("21-review", 345.0, 381.2, WAIT),       # the end of Deploy (321.0 passed), Entry 354.1, TestCall 365.2
            piece("21-review", 381.2, 392.5, ko=[         # approved 381.3, record 382.8, steps_done 387.8 (list_end cuts a
                beat("shot:record", "일곱 단계를 모두 통과한 release_review는 승인이 됩니다")])],    # card: left out)
        "22-works": [
            piece("22-works", 11.0, 15.0),                # change 11.5; the command's typing is cut
            piece("22-works", 19.2, 36.5, ko=[            # asked 19.7, answered 28.1
                beat("answered", "승인된 release_review는 에이전트 게이트웨이로 부르면 바로 답합니다")])],
        "23-reject": [piece("23-reject", 8.7, 43.5, ko=[  # failed 9.2, findings 15.2, reason 23.2, reject_pressed 30.5,
            beat("shot:findings", "플랫폼팀은 스캔이 찾은 취약한 패키지와 고쳐진 버전을 봅니다"),       # job_done 32.6,
            beat("shot:reason", "사유를 적어 반려하면 팀은 레코드에서 그 사유를 읽습니다"),            # rejected 39.6
            beat("job_done", "작업이 끝나자 quality_agent의 레코드가 반려로 바뀝니다")])],
        "24-again": [piece("24-again", 11.8, 31.0, ko=[   # requirements 12.3, publish_quality 18.7, quality_pending 25.1
            beat("shot:requirements", "개발자는 jinja2를 뺀 고친 판을 다시 신청합니다")])],
        "25-approved": [
            piece("25-approved", 4.0, 11.5),              # wide 4.5, steps 9.5
            piece("25-approved", 40.0, 47.5, ko=[         # quality_agent_Scan_passed 41.6
                beat("quality_agent_Scan_passed", "이번에는 Scan이 취약점을 찾지 않고 통과합니다", pos="top")]),
            piece("25-approved", 362.0, 385.3, WAIT),     # Entry passed 362.8, TestCall 367.8, approved 384.8
            piece("25-approved", 385.3, 397.0, ko=[       # record 386.3, steps_done 391.3
                beat("shot:record", "고친 판도 일곱 단계를 모두 통과해 승인이 됩니다")])],
        "26-answers": [piece("26-answers", 11.0, 28.5, ko=[    # asked 11.9, answer 20.1
            beat("shot:answer", "사용자가 묻자 quality_agent는 공유 도구가 돌려준 규격으로 답합니다")])],
        # 3단계: the company policy in log-only mode
        "31-logonly": [
            piece("31-logonly", 9.0, 17.6, ko=[           # off 9.5, logonly_pressed 16.4
                beat("shot:off", "새 전사 정책 guard_prompt를 막지 않는 기록 모드로 겁니다")]),
            piece("31-logonly", 17.6, 36.0, WAIT),        # the job's first lines (it ends at 61.6)
            piece("31-logonly", 61.6, 67.6, ko=[          # job_done 61.6 (the logonly shot 68.6 is left out)
                beat("shot:job_done", "작업이 호스팅된 에이전트마다 정책을 하나씩 붙입니다")]),
            piece("31-logonly", 74.2, 80.5, ko=[          # rows 74.7
                beat("shot:rows", "에이전트 게이트웨이의 세 정책이 기록 모드로 돕니다")])],
        "32-passes": [
            piece("32-passes", 12.0, 19.5, ko=[           # change 12.5; the command's typing is cut
                beat("shot:change", "변경 설명 끝에 에이전트에게 내리는 지시가 들어 있습니다")]),
            piece("32-passes", 24.2, 36.5, ko=[           # asked 24.7, answered 28.3
                beat("answered", "기록 모드에서는 이 요청도 막히지 않고 답을 받습니다")])],
        "33-record": [
            piece("33-record", 8.0, 16.0, ko=[            # report 10.2 (all zero)
                beat("shot:report", "기록 모드의 집계는 정책에 걸린 요청을 에이전트마다 셉니다")]),
            piece("33-record", 16.0, 22.0, WAIT),         # the page redraws until the match is counted
            piece("33-record", 22.0, 31.0, ko=[           # match_counted 22.2
                beat("match_counted", "release_review에 간 그 요청이 막았을 요청 1건으로 잡힙니다")])],
        # 4단계: enforce, the refusals, the custom guardrail before and after
        "41-enforce": [
            piece("41-enforce", 9.7, 19.2, ko=[           # rows_before 10.2, buttons 15.2, enforce_pressed 19.0
                beat("shot:rows_before", "기록 모드로 시험한 정책을 버튼 하나로 적용 모드로 올립니다")]),
            piece("41-enforce", 19.2, 50.0, WAIT),        # the job's first lines (it ends at 88.5)
            piece("41-enforce", 88.4, 94.4),              # job_done 88.5 (the enforced shot 95.5 is left out)
            piece("41-enforce", 100.9, 107.0, ko=[        # rows 101.6
                beat("shot:rows", "이제 세 에이전트의 정책이 모두 적용 모드로 막습니다")])],
        "42-blocked": [
            piece("42-blocked", 12.8, 20.0, ko=[          # refused_release_review 15.0; the next command's typing is cut
                beat("refused_release_review", "같은 요청을 이제 게이트웨이가 403으로 막습니다")]),
            piece("42-blocked", 25.4, 41.5, ko=[          # refused_docs_adk 27.7, both 34.7
                beat("refused_docs_adk", "docs_adk에도 같은 정책이 걸려 있어 똑같이 막힙니다")])],
        "43-before": [
            piece("43-before", 12.6, 24.0, ko=[           # answered_code_name 17.8; the next command's typing is cut
                beat("answered_code_name", "커스텀 가드레일 전에는 사내 코드명이 든 요청도 에이전트에 닿습니다")]),
            piece("43-before", 31.5, 45.5, ko=[           # answered_inspection 37.9
                beat("answered_inspection", "검사 답의 Inspector ID 줄에 사번이 그대로 나옵니다")])],
        "44-attach": [piece("44-attach", 8.7, 35.5, ko=[  # detached 9.1, attach_pressed 16.8, job_done 22.0, attached 29.0
            beat("shot:detached", "커스텀 가드레일을 버튼 하나로 에이전트 게이트웨이에 붙입니다"),
            beat("shot:attached", "커스텀 가드레일이 게이트웨이의 요청과 응답을 모두 검사합니다")])],
        "45-after": [
            piece("45-after", 12.6, 22.5, ko=[            # answered_code_name 16.4; the next command's typing is cut
                beat("answered_code_name", "이제 코드명이 든 요청은 커스텀 가드레일이 막습니다")]),
            piece("45-after", 29.8, 44.0, ko=[            # answered_inspection 36.4
                beat("answered_inspection", "답의 Inspector ID 줄에서는 사번이 가려집니다")])],
        # 5단계: usage, the incident, the alarm, the stop, the cause, the way back
        "51-usage": [piece("51-usage", 10.4, 31.0, ko=[   # agents 10.8, tools 18.8, alarm 24.8
            beat("shot:agents", "플랫폼팀은 에이전트마다 호출과 세션 수를 한 화면에서 봅니다", dur=6.0),
            beat("shot:alarm", "도구 호출 경보는 한 도구의 분당 호출이 19를 넘는지 지켜봅니다")])],
        "52-incident": [
            piece("52-incident", 10.8, 24.0, ko=[         # publish_loop 11.4, submitted 17.8
                beat("shot:submitted", "개발자가 quality_agent의 새 판 v2-loop를 신청합니다")]),
            # its review: only its end. The note approved (376.2) came from the pills; the steps on screen read
            # SUCCEEDED from about 377.8, as the shot approved (377.7) frames the record
            piece("52-incident", 377.6, 382.6, ko=[
                beat("shot:approved", "이 판도 일곱 단계 심사를 모두 통과해 승인이 됩니다")]),
            piece("52-incident", 392.8, 399.0),           # incident_asked 393.1; the 60 s without an answer are cut
            piece("52-incident", 452.8, 461.5, ko=[       # no_answer 454.3
                beat("no_answer", "사용자가 검사 Q-1002를 물었지만 60초가 지나도 답이 없습니다")])],
        "53-alarm": [
            piece("53-alarm", 5.3, 46.2, WAIT),           # alarm 5.7 (OK)
            piece("53-alarm", 46.2, 52.0, ko=[            # first_bar_over 46.9
                beat("first_bar_over", "그 사이 검사 도구의 분당 호출이 임계값 19를 넘습니다")]),
            piece("53-alarm", 88.0, 94.5, WAIT),
            piece("53-alarm", 94.5, 106.5, ko=[           # state_ALARM 95.0, bars 97.0, alarm 103.0
                beat("state_ALARM", "넘는 호출이 이어지자 경보가 ALARM으로 바뀝니다")])],
        "54-stop": [
            piece("54-stop", 9.6, 19.8, ko=[              # agents 10.6, row 14.6, stop_pressed 19.6
                beat("shot:agents", "플랫폼팀은 문제를 일으킨 quality_agent 하나만 멈춥니다")]),
            piece("54-stop", 19.8, 41.6, WAIT),           # the job's lines
            piece("54-stop", 41.6, 55.5, ko=[             # job_done 41.6, stopped 49.6
                beat("shot:job_done", "멈추기는 그 에이전트의 진입을 정책으로 막고 세션을 끝냅니다", dur=6.0)])],
        "55-neighbours": [
            piece("55-neighbours", 11.4, 19.0, ko=[       # quality_agent_HTTP_403 14.0; each next typing is cut
                beat("quality_agent_HTTP_403", "멈춘 quality_agent에 가는 요청은 막힙니다")]),
            piece("55-neighbours", 23.8, 31.5),           # release_review_HTTP_200 28.8
            piece("55-neighbours", 38.4, 58.0, ko=[       # docs_adk_HTTP_200 44.7, all 51.7
                beat("docs_adk_HTTP_200", "이웃 에이전트 release_review와 docs_adk는 그대로 답합니다")])],
        "56-cause": [
            piece("56-cause", 15.8, 31.6, ko=[            # cause_asked 16.8, ask1 24.9 (answered No), the No sentence
                beat("cause_asked", "개발자는 Claude Code에게 같은 도구를 계속 부른 이유를 찾게 합니다")]),
            piece("56-cause", 31.6, 42.2, WAIT),          # work1 33.2: Claude Code reads with its own tools
            # the answer's first line stands still at the top only from 42.2 to 43.0 (cause_done 47.7 less 5.45 s):
            # those real frames play slower, so the line can be read
            piece("56-cause", 42.2, 43.0, 0.13, ko=[
                beat("cause_done", "Claude Code는 로그와 코드를 읽고 재시도에 횟수 제한이 없다고 짚습니다", offset=-5.45)]),
            piece("56-cause", 43.0, 58.0, ko=[            # cause 47.7: the reasons, the way to fix it
                beat("shot:cause", "근거와 함께 고칠 방향을 알려 주고 파일은 고치지 않습니다")])],
        "57-back": [
            piece("57-back", 10.6, 23.0, ko=[             # publish_fixed 11.1, submitted 17.8
                beat("shot:submitted", "개발자는 원인을 고친 판을 다시 신청합니다")]),
            piece("57-back", 356.5, 369.0, ko=[           # its review: only its end (approved 357.0, the shot 358.5,
                beat("approved", "에이전트가 멈춘 동안에도 고친 판의 심사는 끝까지 통과합니다")]),     # steps_done 363.5)
            piece("57-back", 373.0, 382.5, ko=[           # stopped 373.3, row 378.3, resume_pressed 382.3
                beat("shot:stopped", "승인이 끝나도 멈춤은 그대로이고, 재개 버튼으로 다시 엽니다")]),
            piece("57-back", 382.5, 394.0, WAIT),         # the resume job
            piece("57-back", 394.0, 404.5),               # job_done 394.1, running 400.1
            piece("57-back", 419.2, 436.5, ko=[           # asked 419.6, answered 429.6 (the command's typing is cut)
                beat("answered", "같은 질문에 다시 답하고, 사번은 여전히 가려져 있습니다")])],
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
    # a reel names takes and cards; a stage reel is the main reel's run of that stage (stage 1 opens with 준비)
    "reels": {},
}
_STAGE_RUNS = {
    0: ["card-ch0", "00-home"],
    1: ["card-ch1", "11-find", "12-make", "13-submit"],
    2: ["card-ch2", "21-review", "22-works", "23-reject", "24-again", "25-approved", "26-answers"],
    3: ["card-ch3", "31-logonly", "32-passes", "33-record"],
    4: ["card-ch4", "41-enforce", "42-blocked", "43-before", "44-attach", "45-after", "card-compare"],
    5: ["card-ch5", "51-usage", "52-incident", "53-alarm", "54-stop", "55-neighbours", "56-cause", "57-back"],
}
SPEC["reels"] = {"main": ["card-intro", *(n for s in _STAGE_RUNS.values() for n in s), "card-summary", "card-closing"],
                 "stage-1": _STAGE_RUNS[0] + _STAGE_RUNS[1],
                 **{f"stage-{s}": _STAGE_RUNS[s] for s in range(2, 6)}}


# ---------------------------------------------------------------------------------------------------- the rules

def stage(take: str) -> int:
    """The stage of a take: the first digit of its name (00-home is 준비, 12-make is stage 1, 21-review is stage 2)."""
    return int(take[0])


def piece_names(take: str, pieces: list[dict]) -> list[str]:
    """The pieces' file names, <take>.<n> from 1."""
    return [f"{take}.{n}" for n in range(1, len(pieces) + 1)]


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
    for take, pieces in spec["clips"].items():
        for name, part in zip(piece_names(take, pieces), pieces):
            beats = part["beats"].get(lang, [])
            per_stage[stage(take)] += len(beats)
            for b in beats:
                if not isinstance(b["at"], str):
                    found.append(f"{name}: {b['text']!r} is anchored to raw seconds ({b['at']}), not to a shot or a note")
                found += [f"{name}: {b['text']!r} {p}" for p in text_problems(b["text"], True)]
    for s, n in per_stage.items():
        if n > BUDGET[s]:
            found.append(f"{STAGES[s]}: {n} captions, more than its budget of {BUDGET[s]}")
    known = set(spec["clips"]) | set(cards)
    for reel, segments in spec["reels"].items():
        found += [f"reel {reel}: {s!r} is neither a take nor a card of this file" for s in segments if s not in known]
    return found


def anchor_seconds(at: str, log: list[dict]) -> float | None:
    """The camlog second of an anchor as edit_demo.py reads it ('shot:<key>[#n]', 'note:<kind>[#n]', '<kind>[#n]'), or
    None when the camlog holds no such event."""
    spec, _, nth = at.partition("#")
    n = int(nth) if nth else 1
    kind, _, arg = spec.partition(":")
    if kind == "note":
        kind, arg = arg, ""
    hits = [e for e in log if e["kind"] == kind and (kind != "shot" or e.get("key") == arg)]
    return float(hits[n - 1]["t"]) if len(hits) >= n else None


def window_problems(spec: dict, lang: str, raw: Path, takes: set[str]) -> list[str]:
    """Each caption of the given takes against its camlog: the anchor is there, and it falls inside its piece with at
    least ROOM seconds of the finished piece after it."""
    found, logs = [], {}
    for take in sorted(takes):
        pieces = spec["clips"][take]
        for name, part in zip(piece_names(take, pieces), pieces):
            for b in part["beats"].get(lang, []):
                if part["raw"] not in logs:
                    logs[part["raw"]] = json.loads((raw / f"{part['raw']}.camlog.json").read_text())["log"]
                t = anchor_seconds(b["at"], logs[part["raw"]])
                if t is None:
                    found.append(f"{name}: {b['text']!r} is anchored to {b['at']!r}, which the camlog of {part['raw']} "
                                 "does not hold")
                    continue
                t += float(b.get("offset", 0))
                if not part["start"] <= t or (part["end"] - t) / part["speed"] < ROOM:
                    found.append(f"{name}: {b['text']!r} falls at {t:.2f} s, outside its piece {part['start']}.."
                                 f"{part['end']} or less than {ROOM} s of the piece before its end")
    return found


# ---------------------------------------------------------------------------------------- the plugin's script files

def clip_script(part: dict, lang: str) -> dict:
    """edit_demo.py's script for a piece: no title (the chapter cards carry it), the window, the speed, the beats."""
    return {"start": part["start"], "end": part["end"], "speed": part["speed"], "beats": part["beats"].get(lang, [])}


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
    """edit_demo.py's reel: cards and the pieces of each take in order; the pieces of one take meet in hard cuts."""
    segments = []
    for name in spec["reels"][reel]:
        if name not in spec["clips"]:
            segments.append({"file": f"cards/{lang}/{name}.mp4"})
            continue
        names = piece_names(name, spec["clips"][name])
        for i, file in enumerate(names):
            entry = {"file": f"clips/{lang}/{file}.mp4"}
            if i > 0:
                entry["fade_in"] = 0
            if i < len(names) - 1:
                entry["fade_out"] = 0
            segments.append(entry)
    return {"fade": 0.4, "segments": segments}


def reel_seconds(spec: dict, reel: str, lang: str) -> float:
    """A reel's length as the plugin cuts it: each card its seconds, each piece (end - start) / speed."""
    cards = spec["cards"][lang]
    return sum(cards[n]["seconds"] if n in cards else sum((p["end"] - p["start"]) / p["speed"] for p in spec["clips"][n])
               for n in spec["reels"][reel])


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def reel_file(reel: str, lang: str) -> str:
    return f"hosting-hub-{reel}-{lang}"


def clip_command(plugin: Path, name: str, part: dict, lang: str, out: Path) -> list[str]:
    """edit_demo.py clip for one piece. A piece with no beats is cut without captions: the plugin would otherwise burn
    the camera's shot labels, which are notes for the person who records."""
    cmd = [sys.executable, str(plugin / "edit_demo.py"), "clip", str(out / "raw" / f"{part['raw']}.webm"),
           "--script", str(out / "scripts" / lang / f"{name}.json"), "--out", str(out / "clips" / lang / f"{name}.mp4")]
    return cmd + ([] if part["beats"].get(lang) else ["--no-captions"])


# ---------------------------------------------------------------------------------------------------------- run

def run(spec: dict, lang: str = "ko", out: Path = OUT, check_only: bool = False) -> None:
    found = problems(spec, lang)
    if found:
        _stop(found, "text(s) break the rules; nothing was written")
    for take, pieces in spec["clips"].items():
        for name, part in zip(piece_names(take, pieces), pieces):
            write(out / "scripts" / lang / f"{name}.json", clip_script(part, lang))
    write(out / "cards" / lang / "cards.json", {n: {"seconds": card["seconds"], "lines": card_lines(card)}
                                                for n, card in spec["cards"][lang].items()})
    for reel in spec["reels"]:
        write(out / "reels" / f"{reel_file(reel, lang)}.json", reel_manifest(spec, reel, lang))
    parts = [p for pieces in spec["clips"].values() for p in pieces]
    beats = sum(len(p["beats"].get(lang, [])) for p in parts)
    print(f"checked: {len(spec['cards'][lang])} cards, {len(spec['clips'])} takes in {len(parts)} pieces with {beats} "
          f"captions, {len(spec['reels'])} reels; script files in {out}")
    print("reels: " + ", ".join(f"{reel} {int(s // 60)}:{round(s % 60):02d}" for reel in spec["reels"]
                                for s in [reel_seconds(spec, reel, lang)]))
    if check_only:
        return
    plugin = _plugin()
    used = {s for segs in spec["reels"].values() for s in segs} & set(spec["clips"])
    missing = sorted({f"raw/{p['raw']}{ext}" for t in used for p in spec["clips"][t] for ext in (".webm", ".camlog.json")
                      if not (out / "raw" / f"{p['raw']}{ext}").exists()})
    if missing:
        print(f"no raw take for {', '.join(missing)} (under {out}): record it with demo_video/scenes/record.sh",
              file=sys.stderr)
        raise SystemExit(1)
    found = window_problems(spec, lang, out / "raw", used)
    if found:
        _stop(found, "caption(s) do not sit in their pieces; nothing was cut")
    for take in sorted(used):
        for name, part in zip(piece_names(take, spec["clips"][take]), spec["clips"][take]):
            subprocess.run(clip_command(plugin, name, part, lang, out), check=True)
    subprocess.run([sys.executable, str(plugin / "make_cards.py"), str(out / "cards" / lang / "cards.json"),
                    "--out", str(out / "cards" / lang)], check=True)
    for reel in spec["reels"]:
        subprocess.run([sys.executable, str(plugin / "edit_demo.py"), "reel", str(out / "reels" / f"{reel_file(reel, lang)}.json"),
                        "--out", str(out / "reels" / f"{reel_file(reel, lang)}.mp4")], check=True, cwd=out)


def _stop(found: list[str], what: str) -> None:
    for line in found:
        print(line, file=sys.stderr)
    print(f"build stopped: {len(found)} {what}", file=sys.stderr)
    raise SystemExit(2)


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
