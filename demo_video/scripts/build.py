#!/usr/bin/env python3
"""The demo video in one file: per take its pieces (a window of a raw take at one speed, with its captions); the
cards; the six reels.

  python3 demo_video/scripts/build.py --check [--lang ko]    write the plugin's script files and check every text
  python3 demo_video/scripts/build.py [--lang ko]            the same, then cut the clips, the cards and the reels
  python3 demo_video/scripts/build.py --voice --check        the narrated reels' script files, lines and manifests
  python3 demo_video/scripts/build.py --voice                the same, then the voices, clips, reels and their checks

Every caption and card text lives here under a language key. Before anything is written, each text is checked against
the video plugin's rules for captions (references/script.md of the plugin):
  - at most 45 characters; no em dash, middle dot or arrow (U+2014, U+00B7, U+2192); no speed label (a dimension such
    as "M4 x 12 mm" is not one) and no note about the recording;
  - a caption, a chapter's title and a card's row is one sentence in the 합니다 style (it ends in 니다);
  - a caption is anchored to a shot or a note of its take's camlog, never to raw seconds;
  - a stage carries no more captions than its budget (BUDGET);
  - a reel names only takes and cards defined here.
A text that breaks a rule stops the build (exit 2) with one line per text, and so does a key of a caption or a card
that neither build reads (CAPTION_KEYS, CARD_KEYS: a misspelled key would otherwise be dropped without a word).
Without --check the build then measures the takes and reads their camlogs: a piece whose window does not start before
it ends or ends beyond its take, a caption whose anchor the camlog does not hold or that falls outside its piece (or
less than ROOM seconds of the finished piece before its end), and a caption whose "dur" runs into the next caption stop
the build the same way before anything is cut. Then it runs the plugin's
edit_demo.py (clip, reel) and make_cards.py, found through DEMO_VIDEO_PLUGIN (the plugin's scripts folder), with the
Python that runs this file (make_cards.py needs Pillow). In a reel the pieces of one take are joined with hard cuts;
the edges between takes and cards fade (0.4 s). Everything is written under demo_video/out/ (git-ignored):
scripts/<lang>/ and clips/<lang>/ (<take>.<n>, one per piece), cards/<lang>/, reels/ (the manifests next to the reels).

--voice builds the same reels with a spoken narration, beside the silent ones; the silent build never reads the
narration's fields. A caption may carry "say" (its narration), "box" (highlight boxes, as edit_demo.py takes them) with
"what" (one short phrase per box: what it points at), "box_delay", "box_dur" and "voice_at"; a card may carry "say".
READINGS gives the spoken form of an on-screen name, so that the synthesizer gets Hangul only. Before anything is
written, each narration is checked: sentences in the 합니다 style (each ends in 니다.), none of the three characters a
caption may not hold, no Latin letter or digit left once READINGS is applied, on a piece or card that a reel uses; so
are a caption's values: a "what" for each box, "box_delay", "box_dur" and "what" only beside a box, numbers of seconds,
and a box given as numbers, [x, y, w, h], inside the 1920x1080 frame (FRAME).
Then every piece with several captions is split, one caption per piece (a later caption's piece starts SPLIT_LEAD
seconds of the take before its anchor), each caption must still sit in its own piece, and a "voice_at" must lie in its
piece, not before its caption. A narrated caption is held to its piece's last frame (its boxes too, unless "box_dur"
ends them sooner); with "ends_early" (and "dur") its piece ends where the caption ended in the silent video, and the
rest of the window plays on as a piece without a caption, ROOM seconds at least each. Its voice starts VOICE_DELAY
seconds after the caption, a card's VOICE_DELAY seconds into the card; the reel holds a frame until the voice has
ended. Written under demo_video/out/: scripts/<lang>-voice/ and
clips/<lang>-voice/ (<take>.<n>, numbered anew after the split), voice/<lang>/ (lines.json, readings.json, the plugin's
<name>.mp3 and voice.json), reels/hosting-hub-<reel>-<lang>-voice.json and .mp4 (and the plugin's .voice.json),
reports/<reel>-<lang>-voice/ (texts.json, and the plugin's audit.json, boxes/ and review page). The cards are the silent
build's pictures (cards/<lang>/<name>.png), made only when one is missing (from voice/<lang>/cards.json). The plugin's
voice step calls Amazon Polly through the AWS CLI, in the region of the environment. edit_demo.py clip, make_cards.py,
edit_demo.py voice, then per reel edit_demo.py reel and check_demo.py audit, boxes and sheet are run in that order (a
box the clip step refuses stops the build before anything is synthesized); the reel and the audit get the thresholds
VOICE_GAP, VOICE_TAIL, LOUDNESS and VOICE_TOLERANCE, and a failed audit stops the build. Any other of these steps that
fails stops it too (exit 2): the plugin's own lines say why, and one line of the build names the step and its piece,
cards or reel. The narrated build needs demo-video 1.4.0 or later (edit_demo.py voice, voices and pictures in a reel,
check_demo.py).
"""
from __future__ import annotations

import argparse
import copy
import json
import math
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
VOICE_DELAY = 0.3                                       # seconds a narration starts after its caption (or into its card)
SPLIT_LEAD = 0.2                                        # seconds of the take a split piece starts before its caption
SILENT_FIELDS = ("at", "text", "offset", "dur", "pos")  # what a caption passes on to the silent build
VOICED_FIELDS = SILENT_FIELDS + ("box", "box_delay", "box_dur")  # and to the voiced build (it holds a narrated caption)
CAPTION_KEYS = VOICED_FIELDS + ("what", "say", "voice_at", "ends_early")      # every key of a caption the builds read
CARD_KEYS = ("seconds", "kicker", "title", "rows", "accent", "where", "say")  # every key of a card the builds read
VOICES = {"ko": ["--voice", "Seoyeon", "--engine", "generative", "--language", "ko-KR"]}     # Amazon Polly
# the narrated reels' thresholds, given to the plugin: its reel takes the first three, its audit the last two
VOICE_GAP = 0.6                                         # seconds of silence at least between two voices
VOICE_TAIL = 1.0                                        # seconds a reel runs on after its last voice
LOUDNESS = -16.0                                        # integrated loudness of the voices, LUFS
VOICE_TOLERANCE = 0.25                                  # seconds a voice may be heard early or late at either end
# the plugin's clip step, as the voiced build needs it to know where a caption ended in the silent video, when its box
# shows and where a box may lie: a caption shows CAPTION_LEAST seconds at least; a box anchored to a shot waits for the
# camera; a box given as numbers lies inside the frame
CAPTION_LEAST = 1.5                                     # seconds of the finished piece
CAMERA_MOVE = 1.4                                       # seconds of the take the camera takes to arrive on a shot
FRAME = (1920, 1080)                                    # the frame's width and height in pixels, every take's


def piece(raw: str, start: float, end: float, speed: float = DEFAULT_SPEED, ko: list | tuple = ()) -> dict:
    """A piece of a take: the window start..end (seconds of demo_video/out/raw/<raw>.webm, as its camlog counts them)
    at one speed, and its captions per language. A take is one or more pieces, joined in a reel with hard cuts."""
    return {"raw": raw, "start": start, "end": end, "speed": speed, "beats": {"ko": list(ko)}}


def beat(at: str, text: str, **opts) -> dict:
    """A caption (the plugin's beat): anchored to a camlog event, 'shot:<key>[#n]' or '<note kind>[#n]', plus an
    optional "offset" (seconds), "dur" (seconds of the finished piece) and "pos": "top" (edit_demo.py). For the voiced
    build only: "say" (the narration), "box" and "what" (the highlight boxes and, per box, what it points at),
    "box_delay" (seconds after the caption starts), "box_dur" (seconds the boxes show, from their start; without it
    until the caption ends), "voice_at" (seconds into the finished piece; replaces the start computed from the
    anchor), "ends_early": True (with "dur": the narrated caption ends where it ended in the silent video, and the rest
    of its piece plays on without a caption)."""
    return {"at": at, "text": text, **opts}


# Windows are camlog seconds; the comment above each piece names the camlog events it holds. A wait plays at WAIT (a
# job of a few seconds stays at 1.25 inside its piece); a long wait is cut to its start or its end (a hard cut inside
# the take), and so is a stretch of typing in a terminal.
SPEC = {
    "clips": {
        # 준비: the hub screen's home page
        "00-home": [
            # wide 3.9, counts 9.9, flow1 14.9, flow2 21.9, platform 28.9, catalog 35.9
            piece("00-home", 3.5, 41.5, ko=[
                beat("shot:wide", "허브 화면 한 곳에서 호스팅된 에이전트와 공유 도구를 봅니다",
                     say="플랫폼팀이 허브의 지금 상태를 보는 샘플 화면입니다. 홈에는 호스팅된 에이전트 두 개와 승인된 도구 하나가 "
                         "보입니다. 값은 모두 그 순간 AWS에서 읽은 것입니다.",
                     # on the counts once the camera has arrived there (counts 9.9 + 1.4)
                     box=[[23, 224, 375, 166], [1290, 224, 356, 166]], what=["호스팅된 에이전트 수 2", "승인된 도구 수 1"],
                     box_delay=6.0),
                beat("shot:flow1", "흐름 1은 팀이 에이전트를 올리면 허브가 자동으로 심사하는 길입니다",
                     say="흐름 일은 호스팅입니다. 개발팀이 에이전트를 신청하면 호스팅 심사가 자동으로 점검하고, 통과한 에이전트에만 "
                         "도구 권한을 주고 배포합니다."),
                beat("shot:flow2", "흐름 2는 플랫폼팀이 게이트웨이에서 정책을 걸고 지켜보는 길입니다",
                     say="흐름 이는 운영입니다. 사용자의 요청은 에이전트 게이트웨이를 지나고, 플랫폼팀은 그곳에 전사 정책을 "
                         "걸고, 이상한 에이전트를 막습니다."),
                beat("shot:platform", "게이트웨이 둘과 정책 엔진, 카탈로그, 심사 상태 머신을 한 번 만듭니다",
                     say="게이트웨이 둘과 정책 엔진은 AgentCore의 기능입니다. 카탈로그는 AWS Agent Registry, 심사는 "
                         "AWS Step Functions가 돌립니다."),
                beat("shot:catalog", "카탈로그에는 승인된 에이전트와 공유 도구가 올라 있습니다", pos="top",
                     say="카탈로그에는 docs_adk와 spec_assistant, 공유 도구 parts-tools가 승인되어 있습니다. 전사 정책과 "
                         "커스텀 가드레일은 아직 걸려 있지 않습니다.",
                     box=[35, 812, 1271, 173], what=["승인된 카탈로그 레코드 세 줄"])])],
        # 1단계: one Claude Code session (11-find, then 12-make from the note make_asked), then the developer's shell
        "11-find": [
            # find_asked 16.1, record 27.3 (zoomed on the answer)
            piece("11-find", 15.6, 35.0, ko=[
                beat("find_asked", "개발자는 Claude Code에게 부품 규격을 읽는 사내 도구를 찾게 합니다",
                     say="개발자가 Amazon Bedrock의 모델로 도는 Claude Code에게 부탁합니다. 카탈로그의 MCP 서버에서, 부품 "
                         "번호로 규격을 돌려주는 사내 도구를 찾아 달라는 요청입니다."),
                beat("shot:record", "카탈로그의 MCP 서버에서 공유 도구의 이름과 설명, 입력을 찾아 줍니다",
                     say="찾은 것은 승인된 공유 도구 parts-tools에 든 부품 규격 도구입니다. 이름과 설명, 입력인 부품 번호까지 "
                         "알려 줍니다. 카탈로그 검색에는 승인된 것만 나옵니다.",
                     box=[22, 223, 1564, 440], what=["도구 이름과 설명, 입력"])])],
        "12-make": [
            # make_asked 38.3, ask1 41.6, the second question from 46.2 (questions 3 and 4 are left out)
            piece("11-find", 37.9, 47.0, ko=[
                beat("make_asked", "이어서 표준 템플릿으로 그 도구를 쓰는 에이전트를 만들게 합니다", pos="top",
                     say="개발자는 이어서 quality_agent를 만들어 달라고 합니다. 표준 템플릿과 방금 찾은 도구를 쓰는 "
                         "Strands 에이전트이고, 파일만 만들고 실행하거나 올리지는 말라고 적었습니다.")]),
            # ask5 71.3: a long command with 43 hidden lines; the No closes the dialog between 75.7 and 75.8
            piece("11-find", 71.0, 79.4, ko=[
                beat("shot:ask5", "Claude Code는 셸 명령을 실행하기 전에 개발자에게 묻습니다", dur=3.5, pos="top",
                     say="이렇게 Claude Code는 미리 허락되지 않은 셸 명령을 돌리기 전에 묻습니다. 이번 명령은 폴더를 만들고 "
                         "템플릿을 복사해 파일을 쓰는 긴 명령입니다.",
                     # from the stop of the camera's move to shot ask5 (71.27 + 1.4 = 72.67) until the No closes the
                     # dialog after 75.76: the box shows 72.67-75.68 of the take
                     box=[7, 834, 553, 224], what=["실행해도 되는지 묻는 창"], box_delay=1.12, box_dur=2.41)]),
            # work5 79.6: the No and its sentence; then the files are written
            piece("11-find", 79.4, 107.0, WAIT, ko=[
                beat("shot:work5", "개발자는 No로 답하고 실행 없이 파일만 만들게 합니다",
                     say="개발자가 거절하고, 실행하거나 올리지 말고 파일만 만들어 달라고 보냅니다. 그러자 Claude Code는 셸 "
                         "명령 대신 자기 쓰기 도구로 파일을 하나씩 씁니다.")]),
            # made 107.4
            piece("11-find", 107.0, 115.0, ko=[
                beat("shot:made", "Claude Code가 파일 다섯 개를 만들고 올리지는 않았습니다",
                     say="만든 것은 신청서와 에이전트 코드를 포함한 파일 다섯 개이고, 실행도 업로드도 하지 않았습니다. 실제로 "
                         "신청하는 것은 저장소에 미리 준비된 quality_agent입니다.",
                     box=[0, 398, 1373, 68], what=["파일 다섯 개를 만들었다는 줄"])])],
        "13-submit": [
            # publish_release 10.9, release 17.3; the next command's typing is cut
            piece("13-submit", 10.2, 21.5, ko=[
                beat("publish_release", "개발자는 publish 한 줄로 release_review의 호스팅을 신청합니다",
                     say="이제 개발자가 직접 셸에서 신청합니다. publish 명령은 release_review의 코드를 제출함에 올리고 "
                         "카탈로그에 신청서를 써서, 레코드를 승인 대기로 만듭니다.")]),
            # publish_quality 24.4, both 31.1
            piece("13-submit", 23.8, 37.5, ko=[
                beat("shot:both", "quality_agent의 v1-vulnerable 버전도 승인 대기가 됩니다",
                     say="quality_agent는 취약한 라이브러리가 든 변형인 v1-vulnerable로 신청합니다. 이제 두 레코드가 모두 "
                         "승인 대기에 있습니다.")])],
        # 2단계: the reviews on the hub screen, the user's shell, the reject, the second submission
        "21-review": [
            # list 4.9, cards 10.0
            piece("21-review", 4.5, 11.5, ko=[
                beat("shot:list", "신청이 들어오자 두 에이전트의 호스팅 심사가 자동으로 시작됩니다",
                     say="두 에이전트의 심사가 자동으로 시작되어, 둘 다 Scan을 하고 있습니다. Scan은 의존성 검사이고, 심사는 "
                         "AWS Step Functions가 돌립니다.")]),
            # Scan running; release_review's Scan passes at 33.1
            piece("21-review", 30.0, 38.6, WAIT),
            # quality_failed 39.1, quality 40.6, release_card 47.6, steps 54.1
            piece("21-review", 38.6, 60.0, ko=[
                # in the voiced build this caption ends where it ends here (46.82), before the camera moves on to
                # release_review's page (release_card 47.58), and its box ends with it
                beat("shot:quality", "quality_agent의 심사는 의존성 검사 Scan에서 실패해 멈춥니다", dur=5.0, ends_early=True,
                     say="quality_agent는 두 번째 단계인 Scan에서 떨어졌습니다. 의존성 검사가 취약한 패키지를 찾아 심사가 "
                         "멈췄고, 뒤의 단계는 돌지 않습니다. 그동안 release_review는 배포 단계로 넘어갑니다.",
                     box=[21, 524, 1878, 117], what=["Scan 단계 실패 메시지"]),
                beat("shot:steps", "심사 단계마다 AWS Lambda나 AWS CodeBuild가 일을 맡습니다", pos="top",
                     say="제출된 코드를 다루는 Scan과 Deploy는 AWS CodeBuild가, 나머지 단계는 AWS Lambda가 맡습니다. "
                         "Deploy는 에이전트를 AgentCore Runtime에 올리는 단계입니다.",
                     box=[1259, 501, 204, 512], what=["단계마다 일을 맡는 AWS 서비스 열"])]),
            # the end of Deploy (passed 321.0), Entry 354.1, TestCall 365.2
            piece("21-review", 345.0, 381.2, WAIT),
            # approved 381.3, record 382.8, steps_done 387.8 (the shot list_end cuts a card: left out)
            piece("21-review", 381.2, 392.5, ko=[
                beat("shot:record", "일곱 단계를 모두 통과한 release_review는 승인이 됩니다",
                     say="심사가 성공으로 끝나고 release_review의 레코드는 승인으로 바뀌었습니다. 마지막 단계가 사용자의 "
                         "요청을 허용하고 승인으로 표시한 것입니다.",
                     # until the camera moves on to the passed steps (shot steps_done 387.77)
                     box=[7, 268, 279, 54], what=["레코드 상태 승인"], box_dur=2.65)])],
        "22-works": [
            # change 11.5; the command's typing is cut
            piece("22-works", 11.0, 15.0),
            # asked 19.7, answered 28.1
            piece("22-works", 19.2, 36.5, ko=[
                beat("answered", "승인된 release_review는 에이전트 게이트웨이로 부르면 답합니다",
                     say="사용자가 승인된 release_review를 불렀습니다. 변경 설명을 배포 규칙에 비춰 보는 에이전트입니다. "
                         "규칙을 모두 지킨 변경이라 이백과 함께 OK가 돌아옵니다.")])],
        "23-reject": [
            # failed 9.2, findings 15.2, reason 23.2, reject_pressed 30.5, job_done 32.6, rejected 39.6
            piece("23-reject", 8.7, 43.5, ko=[
                beat("shot:findings", "플랫폼팀은 스캔이 찾은 취약한 패키지와 고쳐진 버전을 봅니다",
                     say="심사 페이지에 스캔이 실패한 이유가 나옵니다. Scan의 빌드 로그에서 고른 줄로, jinja2의 이 버전에 "
                         "알려진 취약점 다섯 건과 각각 고쳐진 버전입니다.",
                     box=[870, 373, 630, 221], what=["jinja2 취약점 다섯 줄"]),
                beat("shot:reason", "사유를 적어 반려하면 팀은 레코드에서 그 사유를 읽습니다",
                     say="플랫폼팀이 반려 사유를 적습니다. 이 의존성을 빼거나 고쳐진 버전으로 올린 뒤 다시 신청해 달라는 "
                         "내용입니다.",
                     # until the press changes the page at 29.56 (the camlog's reject_pressed 30.5 comes later)
                     box=[844, 534, 920, 173], what=["반려 사유 입력란"], box_dur=3.7),
                beat("job_done", "작업이 끝나자 quality_agent의 레코드가 반려로 바뀝니다",
                     say="반려 작업이 끝나 레코드가 반려로 바뀌었습니다. 반려는 심사가 남긴 것을 지우는데, Scan에서 멈춘 이 "
                         "신청은 만든 것이 없어 지울 것도 없다고 나옵니다.",
                     # the camera moves to the job (shot job_done) as the job ends
                     box=[47, 170, 344, 73], what=["레코드 반려와 지울 것 없음 두 줄"], box_delay=1.32, box_dur=4.25)])],
        "24-again": [
            # requirements 12.3, publish_quality 18.7, quality_pending 25.1
            piece("24-again", 11.8, 31.0, ko=[
                beat("shot:requirements", "개발자는 jinja2를 뺀 고친 버전을 다시 신청합니다",
                     say="개발자는 고친 버전의 의존성 목록부터 보여 줍니다. 문제가 된 jinja2는 목록에 없습니다. 이 버전을 "
                         "publish로 다시 올리자, 같은 레코드가 다시 승인 대기가 됩니다.")])],
        "25-approved": [
            # wide 4.5, steps 9.5
            piece("25-approved", 4.0, 11.5),
            # quality_agent_Scan_passed 41.6
            piece("25-approved", 40.0, 47.5, ko=[
                beat("quality_agent_Scan_passed", "이번에는 Scan이 취약점을 찾지 않고 통과합니다", pos="top",
                     say="다시 신청하자 심사도 새로 돌았습니다. 이번에는 Scan이 통과해 실행 역할과 도구 권한을 만드는 "
                         "단계로 넘어가고, 이어서 AgentCore Runtime에 배포하고 시험 호출까지 지납니다.",
                     # the camera moves to the steps (shot steps) at the note
                     box=[118, 572, 1693, 64], what=["Scan 통과 줄"], box_delay=1.32)]),
            # Entry passed 362.8, TestCall 367.8, approved 384.8
            piece("25-approved", 362.0, 385.3, WAIT),
            # record 386.3, steps_done 391.3
            piece("25-approved", 385.3, 397.0, ko=[
                beat("shot:record", "고친 버전도 일곱 단계를 모두 통과해 승인이 됩니다",
                     say="심사가 성공으로 끝나고, quality_agent의 레코드도 승인이 되었습니다. 같은 레코드가 반려를 거쳐 "
                         "승인까지 온 것입니다.",
                     # until the camera moves on to the passed steps (shot steps_done 391.34)
                     box=[7, 459, 279, 51], what=["레코드 상태 승인"], box_dur=2.65)])],
        "26-answers": [
            # asked 11.9, answer 20.1
            piece("26-answers", 11.0, 28.5, ko=[
                beat("shot:answer", "사용자가 묻자 quality_agent는 공유 도구가 돌려준 규격으로 답합니다",
                     say="사용자가 quality_agent에게 부품 P-100의 규격을 묻습니다. 에이전트는 도구 게이트웨이를 거쳐 공유 "
                         "도구를 부르고, 돌려받은 크기와 재질로 답합니다.")])],
        # 3단계: the company policy in log-only mode
        "31-logonly": [
            # off 9.5, logonly_pressed 16.4
            piece("31-logonly", 9.0, 17.6, ko=[
                beat("shot:off", "새 전사 정책 guard_prompt를 막지 않는 기록 모드로 겁니다",
                     say="플랫폼팀이 새 전사 정책을 준비했습니다. 프롬프트에 숨은 공격을 잡아내는 guard_prompt 정책입니다. "
                         "처음에는 요청을 막지 않는 기록 모드로 겁니다.",
                     # until the press redraws the page at 15.48 (the camlog's logonly_pressed 16.37 comes later)
                     box=[366, 330, 740, 144], what=["guard_prompt 정책과 설명"], box_dur=3.35)]),
            # the job's first lines (it ends at 61.6)
            piece("31-logonly", 17.6, 36.0, WAIT),
            # job_done 61.6 (the shot logonly 68.6 is left out)
            piece("31-logonly", 61.6, 67.6, ko=[
                beat("shot:job_done", "작업이 호스팅된 에이전트마다 정책을 하나씩 붙입니다",
                     say="버튼 한 번으로, 호스팅된 에이전트마다 같은 정책이 하나씩 붙었습니다. 정책은 게이트웨이가 따르는 "
                         "정책 엔진에 들어갑니다.",
                     box=[47, 171, 345, 179], what=["에이전트마다 정책을 붙인 작업 줄"])]),
            # rows 74.7
            piece("31-logonly", 74.2, 80.5, ko=[
                beat("shot:rows", "에이전트 게이트웨이의 세 정책이 기록 모드로 걸려 있습니다",
                     say="에이전트 게이트웨이에 정책 세 개가 기록 모드로 걸려 있습니다. 이제 들어오는 요청은 이 정책의 "
                         "검사를 받습니다.",
                     box=[16, 456, 1888, 168], what=["기록 모드로 걸린 정책 세 줄"])])],
        "32-passes": [
            # change 12.5; the command's typing is cut
            piece("32-passes", 12.0, 19.5, ko=[
                beat("shot:change", "변경 설명 끝에 에이전트에게 내리는 지시가 들어 있습니다",
                     say="사용자가 release_review 에이전트에게 변경 설명을 보냅니다. 그런데 설명 끝에, 이전 지시를 모두 "
                         "무시하라는 문장이 들어 있습니다.")]),
            # asked 24.7, answered 28.3
            piece("32-passes", 24.2, 36.5, ko=[
                beat("answered", "기록 모드에서는 이 요청도 막히지 않고 답을 받습니다",
                     say="기록 모드이기 때문에 이 요청은 막히지 않습니다. 에이전트는 평소처럼 답합니다.")])],
        "33-record": [
            # report 10.2 (all zero)
            piece("33-record", 8.0, 16.0, ko=[
                beat("shot:report", "기록 모드의 집계는 정책에 걸린 요청을 에이전트마다 셉니다",
                     say="플랫폼팀은 정책 화면에서 기록 모드의 집계를 봅니다. 정책에 걸린 요청이 에이전트마다 몇 건인지 "
                         "세어 줍니다.")]),
            # the page redraws until the match is counted
            piece("33-record", 16.0, 22.0, WAIT),
            # match_counted 22.2
            piece("33-record", 22.0, 31.0, ko=[
                beat("match_counted", "release_review에 간 그 요청이 막았을 요청 1건으로 잡힙니다",
                     say="방금 그 요청이 release_review 에이전트에서 한 건으로 잡혔습니다. 적용 모드였다면 막혔을 "
                         "요청입니다. 이렇게 먼저 확인한 뒤에 정책을 적용합니다.",
                     # after the camlog's second shot report (23.71), which frames the same view
                     box=[281, 726, 1356, 75], what=["release_review의 1건"], box_delay=1.24)])],
        # 4단계: enforce, the refusals, the custom guardrail before and after
        "41-enforce": [
            # rows_before 10.2, buttons 15.2, enforce_pressed 19.0
            piece("41-enforce", 9.7, 19.2, ko=[
                beat("shot:rows_before", "기록 모드로 시험한 정책을 버튼 하나로 적용 모드로 올립니다",
                     say="기록 모드에서 막았을 요청을 확인했으니, 이제 같은 정책을 적용 모드로 올립니다. 정책을 새로 만들지 "
                         "않고, 모드만 바꾸는 작업이 시작됩니다.",
                     # until the camera moves on to the policy's buttons (shot buttons 15.17)
                     box=[16, 456, 1888, 168], what=["기록 모드인 정책 세 줄"], box_dur=2.65)]),
            # the job's first lines (it ends at 88.5)
            piece("41-enforce", 19.2, 50.0, WAIT),
            # job_done 88.5 (the shot enforced 95.5 is left out)
            piece("41-enforce", 88.4, 94.4),
            # rows 101.6
            piece("41-enforce", 100.9, 107.0, ko=[
                beat("shot:rows", "이제 세 에이전트의 정책이 모두 적용 모드로 막습니다",
                     say="프롬프트 공격 차단 정책 세 줄이 모두 적용 모드입니다. 이제 이 정책에 걸린 요청은 게이트웨이에서 "
                         "거부되어 에이전트에 닿지 않습니다.",
                     box=[16, 456, 1888, 168], what=["적용 모드로 바뀐 정책 세 줄"])])],
        "42-blocked": [
            # refused_release_review 15.0; the next command's typing is cut
            piece("42-blocked", 12.8, 20.0, ko=[
                beat("refused_release_review", "같은 요청을 이제 게이트웨이가 403으로 막습니다",
                     say="기록 모드에서 지나갔던 같은 파일을 다시 보냅니다. 이번에는 사공삼으로 거부되고, 이유에 "
                         "guard_prompt 정책이 적혀 있습니다.")]),
            # refused_docs_adk 27.7, both 34.7
            piece("42-blocked", 25.4, 41.5, ko=[
                beat("refused_docs_adk", "docs_adk에도 같은 정책이 걸려 있어 똑같이 막힙니다",
                     say="처음부터 올라와 있던 docs_adk에 보내도 똑같이 사공삼입니다. docs_adk는 Google ADK, "
                         "release_review는 LangGraph로 만들었지만, 전사 정책은 그 앞의 게이트웨이에서 걸립니다.")])],
        "43-before": [
            # answered_code_name 17.8; the next command's typing is cut
            piece("43-before", 12.6, 24.0, ko=[
                beat("answered_code_name", "커스텀 가드레일 전에는 사내 코드명이 든 요청도 에이전트에 닿습니다",
                     say="코드명 Project Falcon이 든 질문입니다. 밖으로 나가면 안 되는 코드명이지만, 아직은 이백으로 "
                         "에이전트까지 닿아 답이 옵니다.")]),
            # answered_inspection 37.9
            piece("43-before", 31.5, 45.5, ko=[
                beat("answered_inspection", "검사 답의 Inspector ID 줄에 사번이 그대로 나옵니다",
                     say="검사 Q-1001의 결과를 묻자, 답의 검사자 줄에 직원의 사번이 그대로 실려 옵니다. 샘플 도구가 만든 "
                         "값이지만, 사번은 회사 밖으로 나가면 안 되는 값입니다.")])],
        "44-attach": [
            # detached 9.1, attach_pressed 16.8, job_done 22.0 (a short job: it plays at 1.25), attached 29.0
            piece("44-attach", 8.7, 35.5, ko=[
                beat("shot:detached", "커스텀 가드레일을 버튼 하나로 에이전트 게이트웨이에 붙입니다",
                     say="이번에는 회사만의 규칙을 거는 커스텀 가드레일입니다. 에이전트 게이트웨이에 붙는 AWS Lambda "
                         "인터셉터로, 요청과 응답을 Amazon Bedrock Guardrails로 검사합니다.",
                     # until the press redraws the page at 15.78 (the camlog's attach_pressed 16.8 comes later)
                     box=[366, 300, 1399, 129], what=["커스텀 가드레일과 설명"], box_dur=3.95),
                beat("shot:attached", "커스텀 가드레일이 게이트웨이의 요청과 응답을 모두 검사합니다",
                     say="상태가 붙어 있음으로 바뀌었고, 붙은 지점은 요청과 응답 두 곳입니다. 이제 에이전트 게이트웨이 "
                         "뒤의 모든 에이전트가 이 검사를 받습니다.",
                     box=[366, 432, 526, 143], what=["붙어 있음과 붙은 지점"])])],
        "45-after": [
            # answered_code_name 16.4; the next command's typing is cut
            piece("45-after", 12.6, 22.5, ko=[
                beat("answered_code_name", "이제 코드명이 든 요청은 커스텀 가드레일이 막습니다",
                     say="같은 코드명 질문을 다시 보내자 이번에는 사공삼입니다. 회사 가드레일인 인터셉터가 요청을 막았다는 "
                         "문장이 나옵니다.")]),
            # answered_inspection 36.4
            piece("45-after", 29.8, 44.0, ko=[
                beat("answered_inspection", "답의 Inspector ID 줄에서는 사번이 가려집니다",
                     say="검사 질문은 이번에도 답을 받지만, 검사자 줄에는 사번 대신 가린 표시가 나옵니다. 커스텀 "
                         "가드레일이 돌아오는 답에서 사번 형식의 값을 찾아 가린 것입니다.")])],
        # 5단계: usage, the incident, the alarm, the stop, the cause, the way back
        "51-usage": [
            # agents 10.8, tools 18.8, alarm 24.8
            piece("51-usage", 10.4, 31.0, ko=[
                beat("shot:agents", "플랫폼팀은 에이전트마다 호출과 세션 수를 한 화면에서 봅니다", dur=6.0,
                     say="에이전트 페이지는 호스팅된 에이전트마다 최근 육십 분의 호출과 세션 수를 Amazon CloudWatch에서 "
                         "읽어 보여 줍니다. 그 아래에는 도구 게이트웨이를 지난 도구별 호출 수가 있습니다.",
                     # until the camera moves on to the calls of each tool (shot tools 18.83)
                     box=[945, 370, 135, 356], what=["에이전트마다의 호출과 세션 수"], box_dur=5.0),
                beat("shot:alarm", "도구 호출 경보는 한 도구의 분당 호출이 19를 넘는지 지켜봅니다",
                     say="지켜보는 것은 검사 건을 읽는 도구이고, 지금은 정상입니다. 같은 질문을 쉬지 않고 되묻는 에이전트가 "
                         "있으면 호출이 크게 늘어 경보가 울립니다.",
                     box=[23, 339, 476, 170], what=["정상 상태와 감시하는 도구"])])],
        "52-incident": [
            # publish_loop 11.4, submitted 17.8
            piece("52-incident", 10.8, 24.0, ko=[
                beat("shot:submitted", "개발자가 quality_agent의 새 버전 v2-loop를 신청합니다",
                     say="이번에는 이미 승인된 quality_agent의 새 버전을 올립니다. v2-loop는 도구를 반복 호출하는 사고를 "
                         "일부러 내도록 만든 데모용 버전입니다.")]),
            # its review: only its end. The note approved (376.2) came from the pills; the steps on screen read
            # SUCCEEDED from about 377.8, as the shot approved (377.7) frames the record
            piece("52-incident", 377.6, 382.6, ko=[
                beat("shot:approved", "이 버전도 일곱 단계 심사를 모두 통과해 승인이 됩니다",
                     say="이 버전도 일곱 단계를 모두 지나 승인됩니다. 심사의 시험 호출에는 반복하지 않았기 때문입니다. 이어서 "
                         "사용자가 검사 건 하나의 결과를 묻습니다.",
                     box=[7, 432, 279, 50], what=["레코드 상태 승인"])]),
            # incident_asked 393.1; the 60 s without an answer are cut
            piece("52-incident", 392.8, 399.0),
            # no_answer 454.3
            piece("52-incident", 452.8, 461.5, ko=[
                beat("no_answer", "사용자가 검사 Q-1002를 물었지만 60초가 지나도 답이 없습니다",
                     say="답 대신 시간이 다 됐다는 한 줄만 나옵니다. 그사이 에이전트는 같은 질문을 쉬지 않고 다시 묻고, "
                         "호출한 쪽이 포기한 뒤에도 그 반복은 계속됩니다.")])],
        "53-alarm": [
            # alarm 5.7 (OK)
            piece("53-alarm", 5.3, 46.2, WAIT),
            # first_bar_over 46.9
            piece("53-alarm", 46.2, 52.0, ko=[
                beat("first_bar_over", "그 사이 검사 도구의 분당 호출이 임계값 19를 넘습니다",
                     say="경보의 막대 하나가 임계값 선을 넘었습니다. 한 분 동안 검사 도구가 스물일곱 번 불린 것인데, 이때 "
                         "경보 상태는 아직 정상입니다.",
                     # the camera moves to the alarm (shot alarm) at the note
                     box=[1698, 427, 89, 350], what=["임계값을 넘은 막대 27"], box_delay=1.32)]),
            piece("53-alarm", 88.0, 94.5, WAIT),
            # state_ALARM 95.0, bars 97.0, alarm 103.0 (one bar, 27, over the line in this take)
            piece("53-alarm", 94.5, 106.5, ko=[
                beat("state_ALARM", "임계값을 넘은 뒤 경보 상태가 ALARM으로 바뀝니다",
                     say="Amazon CloudWatch 경보가 경보 중으로 바뀌고, 허브의 알림 주제로 알림이 나갑니다. 경보는 알리기만 "
                         "하고, 에이전트를 멈추는 일은 플랫폼팀이 정합니다.")])],
        "54-stop": [
            # agents 10.6, row 14.6, stop_pressed 19.6
            piece("54-stop", 9.6, 19.8, ko=[
                beat("shot:agents", "플랫폼팀은 문제를 일으킨 quality_agent 하나만 멈춥니다",
                     say="경보를 본 플랫폼팀이 quality_agent 줄의 멈추기를 누릅니다. 작업은 먼저 이 "
                         "에이전트의 진입을 막는 정책을 거는데, 심사의 시험 호출만은 예외로 둡니다.")]),
            # the job's lines
            piece("54-stop", 19.8, 41.6, WAIT),
            # job_done 41.6, stopped 49.6
            piece("54-stop", 41.6, 55.5, ko=[
                beat("shot:job_done", "멈추기는 그 에이전트의 진입을 정책으로 막고 세션을 끝냅니다", dur=6.0,
                     say="진입을 막는 정책이 켜진 뒤, 작업은 최근 삼십 분 동안 로그가 남은 세션을 찾아 하나씩 끝냅니다. "
                         "이제 quality_agent만 멈춤이고, 나머지 에이전트는 그대로 동작 중입니다.",
                     # on the last shot (stopped 49.6 + 1.4)
                     box=[792, 424, 127, 223], what=["멈춤과 동작 중 상태"], box_delay=7.75)])],
        "55-neighbours": [
            # quality_agent_HTTP_403 14.0; each next command's typing is cut
            piece("55-neighbours", 11.4, 19.0, ko=[
                beat("quality_agent_HTTP_403", "멈춘 quality_agent에 가는 요청은 막힙니다",
                     say="멈춘 quality_agent에 평소의 규격 질문을 보내자 사공삼으로 거부되고, 이유에 멈춤 정책의 이름이 "
                         "나옵니다. 이어서 이웃 에이전트 release_review를 부릅니다.")]),
            # release_review_HTTP_200 28.8
            piece("55-neighbours", 23.8, 31.5),
            # docs_adk_HTTP_200 44.7, all 51.7
            piece("55-neighbours", 38.4, 58.0, ko=[
                beat("docs_adk_HTTP_200", "이웃 에이전트 release_review와 docs_adk는 그대로 답합니다",
                     say="release_review는 이백과 함께 OK로 답했고, docs_adk도 API 버전 표준을 묻는 질문에 답합니다. "
                         "멈춤은 그 에이전트의 진입에만 걸리므로 이웃은 영향을 받지 않습니다.")])],
        "56-cause": [
            # cause_asked 16.8, ask1 24.9 (answered No), the No sentence
            piece("56-cause", 15.8, 31.6, ko=[
                beat("cause_asked", "개발자는 Claude Code에게 같은 도구를 계속 부른 이유를 찾게 합니다",
                     say="개발자가 Claude Code에게 로그와 올린 v2-loop 버전의 코드를 읽고 원인을 찾아 달라고 합니다. 파일을 "
                         "고치거나 다른 명령을 돌리지는 말라고 했고, 묻는 셸 명령은 이번에도 거절합니다.")]),
            # work1 33.2: Claude Code reads with its own tools
            piece("56-cause", 31.6, 42.2, WAIT),
            # the answer's first line stands still at the top only from 42.2 to 43.0 (cause_done 47.7 less 5.45 s):
            # those real frames play slower, so the line can be read
            piece("56-cause", 42.2, 43.0, 0.13, ko=[
                beat("cause_done", "Claude Code는 로그와 코드에서 재시도 횟수 제한이 없다는 원인을 찾습니다", offset=-5.45,
                     say="검사 결과가 계속 대기 상태라, v2-loop 버전이 횟수 제한 없이 같은 질문을 다시 물었다는 답입니다. "
                         "근거로 로그와 코드, 그 파일의 주석까지 듭니다.")]),
            # cause 47.7: the reasons, the way to fix it
            piece("56-cause", 43.0, 58.0, ko=[
                beat("shot:cause", "근거와 함께 고칠 방향을 알려 주고 파일은 고치지 않습니다",
                     say="답은 한계도 밝힙니다. 결과가 대기 상태였다는 것은 로그가 아니라 코드에서 추정했다는 것입니다. "
                         "고칠 방향으로는 재시도 횟수의 상한과 대기를 제안하고, 파일은 고치지 않았습니다.",
                     # while its second sentence speaks of it; the third is about the way to fix it, below
                     box=[20, 569, 1580, 202], what=["답의 한계 부분"], box_dur=5.65)])],
        "57-back": [
            # publish_fixed 11.1, submitted 17.8
            piece("57-back", 10.6, 23.0, ko=[
                beat("shot:submitted", "개발자는 원인을 고친 버전을 다시 신청합니다",
                     say="이번에는 변형 없이 quality_agent를 다시 올립니다. 반복 호출하는 v2-loop가 아닌 기본 버전이고, "
                         "레코드는 다시 승인 대기가 됩니다.")]),
            # its review: only its end (approved 357.0, the shot approved 358.5, steps_done 363.5)
            piece("57-back", 356.5, 369.0, ko=[
                beat("approved", "에이전트가 멈춘 동안에도 고친 버전의 심사는 끝까지 통과합니다",
                     say="새 버전의 심사가 일곱 단계를 모두 지나 성공했습니다. 멈춤 정책이 심사의 시험 호출만은 예외로 "
                         "들여보내기 때문에, 멈춘 동안에도 시험 호출 단계가 지나갑니다.")]),
            # stopped 373.3, row 378.3, resume_pressed 382.3
            piece("57-back", 373.0, 382.5, ko=[
                beat("shot:stopped", "승인이 끝나도 멈춤은 그대로이고, 재개 버튼으로 다시 엽니다",
                     say="심사는 멈춤 정책을 지우지 않으므로, 승인된 뒤에도 quality_agent는 멈춤입니다. 플랫폼팀이 재개를 "
                         "누르면 그 정책 하나만 지워지고, 경보도 정상으로 돌아와 있습니다.",
                     # until the camera moves on to quality_agent's row and its resume button (shot row 378.29)
                     box=[38, 502, 1467, 89], what=["멈춤인 quality_agent 줄"], box_dur=2.65)]),
            # the resume job
            piece("57-back", 382.5, 394.0, WAIT),
            # job_done 394.1, running 400.1
            piece("57-back", 394.0, 404.5),
            # asked 419.6 (stage 4's inspection question, Q-1001), answered 429.6; the command's typing is cut
            piece("57-back", 419.2, 436.5, ko=[
                beat("answered", "재개한 quality_agent가 다시 답하고, 사번은 여전히 가려집니다",
                     say="quality_agent가 다시 이백으로 답합니다. 사번이 가려진 것은 사단계에서 붙인 커스텀 가드레일이 지금도 "
                         "붙어 있기 때문입니다.")])],
    },
    # a card: kicker, title, and either rows (sentences; "accent" = the index of the accented row) or, for a chapter
    # card, "where" (the place the chapter happens, a name rather than a sentence); "say" is its narration
    "cards": {
        "ko": {
            "card-intro": {"seconds": 4, "kicker": "AI 에이전트 호스팅 허브 on Amazon Bedrock AgentCore",
                           "title": "팀은 스스로 올리고, 플랫폼팀은 한 곳에서 관리합니다", "rows": [],
                           "say": "Amazon Bedrock AgentCore 위에 만든 AI 에이전트 호스팅 허브입니다. 여러 팀이 자기 에이전트를 "
                                  "스스로 올리고, 플랫폼팀은 한 곳에서 관리합니다."},
            "card-ch0": {"seconds": 3, "kicker": "준비", "title": "플랫폼팀이 허브를 한 번 만들어 둡니다",
                         "where": "허브 화면의 홈",
                         "say": "먼저 준비 단계입니다. 플랫폼팀이 게이트웨이와 정책, 카탈로그로 이루어진 허브를 한 번 만들어 둡니다."},
            "card-ch1": {"seconds": 3, "kicker": "1단계. 호스팅 신청", "title": "팀은 플랫폼팀 없이 찾고, 만들고, 신청합니다",
                         "where": "Claude Code와 AWS Agent Registry",
                         "say": "일단계는 호스팅 신청입니다. 개발팀은 플랫폼팀을 거치지 않고 도구를 찾고, 에이전트를 만들고, "
                                "신청합니다."},
            "card-ch2": {"seconds": 3, "kicker": "2단계. 호스팅 심사", "title": "신청이 들어오면 허브가 자동으로 심사합니다",
                         "where": "심사 파이프라인과 AgentCore Runtime",
                         "say": "이단계는 호스팅 심사입니다. 신청이 들어오면 허브가 자동으로 심사하고, 통과한 에이전트만 "
                                "AgentCore Runtime에 올립니다."},
            "card-ch3": {"seconds": 3, "kicker": "3단계. 전사 정책 시험", "title": "새 전사 정책을 막지 않고 먼저 시험합니다",
                         "where": "Policy in AgentCore의 기록 모드",
                         "say": "삼단계는 전사 정책 시험입니다. 새 정책을 바로 적용하지 않고, 먼저 기록 모드로 시험합니다."},
            "card-ch4": {"seconds": 3, "kicker": "4단계. 전사 정책 적용", "title": "전사 정책 하나가 모든 에이전트에 걸립니다",
                         "where": "AgentCore Gateway와 커스텀 가드레일",
                         "say": "사단계는 전사 정책 적용입니다. 시험을 마친 정책 하나를 적용 모드로 올리면 모든 에이전트에서 "
                                "막습니다."},
            "card-ch5": {"seconds": 3, "kicker": "5단계. 이상 대응", "title": "문제를 일으킨 에이전트 하나만 멈춥니다",
                         "where": "CloudWatch 경보와 AgentCore Runtime",
                         "say": "오단계는 이상 대응입니다. 경보가 울리면 문제를 일으킨 에이전트 하나만 멈추고, 다른 에이전트는 "
                                "그대로 둡니다."},
            "card-compare": {"seconds": 8, "kicker": "가드레일 두 가지", "title": "기본 제공 가드레일과 커스텀 가드레일",
                             "rows": ["기본 제공은 설정으로 걸고 기록 모드로 먼저 시험합니다",
                                      "커스텀은 사내 코드로 막고 민감 정보를 가립니다",
                                      "둘 다 게이트웨이에 걸려 모든 에이전트에 적용됩니다"], "accent": 2,
                             "say": "기본 제공 가드레일은 설정으로 걸고, 기록 모드로 먼저 시험합니다. 커스텀 가드레일은 사내 "
                                    "코드로 막고 민감 정보를 가립니다. 둘 다 게이트웨이에 걸려 모든 에이전트에 적용됩니다."},
            "card-summary": {"seconds": 9, "kicker": "정리", "title": "팀은 스스로 올리고, 플랫폼팀은 한 곳에서 관리합니다",
                             "rows": ["팀은 카탈로그에서 찾고 템플릿으로 만들어 스스로 신청합니다",
                                      "허브가 자동으로 심사하고 통과한 것만 올립니다",
                                      "전사 정책은 게이트웨이에 한 번 걸면 모두에 적용됩니다",
                                      "이상 에이전트 하나만 멈추고 이웃은 계속 답합니다"], "accent": 3,
                             "say": "팀은 스스로 찾고 만들어 신청하고, 허브는 자동으로 심사해 통과한 것만 올립니다. 전사 정책은 "
                                    "게이트웨이에 한 번 걸면 모두에 걸립니다. 이상 에이전트 하나만 멈추고 이웃은 계속 답합니다."},
            "card-closing": {"seconds": 7, "kicker": "누가 무엇을 맡나", "title": "AgentCore가 주는 것과 플랫폼팀이 만드는 것",
                             "rows": ["AgentCore는 Runtime, Gateway, Policy를 줍니다",
                                      "AgentCore는 Registry와 관측도 줍니다",
                                      "플랫폼팀은 심사 파이프라인과 운영 명령, 허브 화면을 만듭니다"],
                             "say": "AgentCore는 Runtime과 Gateway, Policy, 그리고 Registry와 관측을 줍니다. 플랫폼팀은 그 위에 "
                                    "심사 파이프라인과 운영 명령, 허브 화면을 만듭니다."},
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

# how a narration speaks an on-screen name or a number, per language: the plugin's voice step replaces each name by its
# reading (the longest name first) before the text goes to the synthesizer, which then gets Hangul only
READINGS: dict[str, dict[str, str]] = {"ko": {
    "Amazon Bedrock AgentCore": "아마존 베드록 에이전트코어",
    "Amazon Bedrock": "아마존 베드록",
    "Amazon Bedrock Guardrails": "아마존 베드록 가드레일",
    "AgentCore": "에이전트코어",
    "Gateway": "게이트웨이",
    "AWS Agent Registry": "에이더블유에스 에이전트 레지스트리",
    "AWS Step Functions": "에이더블유에스 스텝 펑션스",
    "AWS Lambda": "에이더블유에스 람다",
    "AWS CodeBuild": "에이더블유에스 코드빌드",
    "AWS": "에이더블유에스",
    "Amazon CloudWatch": "아마존 클라우드워치",
    "Runtime": "런타임",
    "Policy": "폴리시",
    "Registry": "레지스트리",
    "Scan": "스캔",
    "Deploy": "디플로이",
    "AI": "에이아이",
    "docs_adk": "독스 에이디케이",
    "spec_assistant": "스펙 어시스턴트",
    "parts-tools": "파츠 툴즈",
    "guard_prompt": "가드 프롬프트",
    "Claude Code": "클로드 코드",
    "MCP": "엠씨피",
    "Strands": "스트랜즈",
    "quality_agent": "퀄리티 에이전트",
    "release_review": "릴리스 리뷰",
    "publish": "퍼블리시",
    "v1-vulnerable": "브이 원 벌너러블",
    "jinja2": "진자 투",
    "OK": "오케이",
    "P-100": "피 백",
    "Google ADK": "구글 에이디케이",
    "LangGraph": "랭그래프",
    "Project Falcon": "프로젝트 팰컨",
    "Q-1001": "큐 천일",
    "v2-loop": "브이 투 루프",
    "API": "에이피아이",
}}


# ---------------------------------------------------------------------------------------------------- the rules

def stage(take: str) -> int:
    """The stage of a take: the first digit of its name (00-home is 준비, 12-make is stage 1, 21-review is stage 2)."""
    return int(take[0])


def piece_names(take: str, pieces: list[dict]) -> list[str]:
    """The pieces' file names, <take>.<n> from 1."""
    return [f"{take}.{n}" for n in range(1, len(pieces) + 1)]


def _pieces(spec: dict) -> list[tuple[str, dict]]:
    """(<take>.<n>, piece) for every piece of a spec, take by take."""
    return [(name, part) for take, pieces in spec["clips"].items()
            for name, part in zip(piece_names(take, pieces), pieces)]


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


def key_problems(item: dict, known: tuple[str, ...], kind: str) -> list[str]:
    """Each key of a caption or a card that neither build reads, one line each: a misspelled "ends_early" or
    "box_dur", or a "box" on a card, would otherwise be dropped without a word."""
    return [f"the key {k!r} is not one the build knows ({kind}'s keys: {', '.join(known)})"
            for k in item if k not in known]


def problems(spec: dict, lang: str) -> list[str]:
    found = []
    if lang not in spec["cards"]:
        return [f"no texts in the language {lang!r} (there are: {', '.join(sorted(spec['cards']))})"]
    cards = spec["cards"][lang]
    for name, card in cards.items():
        found += [f"{name}: {p}" for p in key_problems(card, CARD_KEYS, "a card")]
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
                found += [f"{name}: {b['text']!r}: {p}" for p in key_problems(b, CAPTION_KEYS, "a caption")]
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


def used_names(spec: dict) -> set[str]:
    """The takes and cards that at least one reel names."""
    return {s for segments in spec["reels"].values() for s in segments}


def spoken(text: str, readings: dict[str, str]) -> str:
    """A narration as the synthesizer gets it: the plugin's rule for readings (edit_demo.py voice --readings), plain
    substrings, the longest first, each place replaced once."""
    keys = sorted((k for k in readings if k), key=len, reverse=True)
    return re.sub("|".join(map(re.escape, keys)), lambda m: readings[m.group(0)], text) if keys else text


def box_count(box) -> int:
    """How many rectangles a beat's "box" draws: [x, y, w, h], a list of them, or one 'shot:<key>' / 'mark:<key>'."""
    if not isinstance(box, (list, tuple)):
        return 0 if box is None else 1
    return 0 if not box else len(box) if isinstance(box[0], (list, tuple)) else 1


def say_problems(say, lang: str) -> list[str]:
    """What is wrong with one narration: it is sentences in the 합니다 style (each ends in 니다., the last may leave out
    its full stop), holds none of the three characters a caption may not hold, and is Hangul only once READINGS is
    applied. A narration has no length limit."""
    if not isinstance(say, str) or not say.strip():
        return ["the narration is empty"]
    found = []
    sentences = re.split(r"(?<=[.?!])\s+", say.strip())
    for i, s in enumerate(sentences):
        if not (s.endswith("니다.") or (i == len(sentences) - 1 and s.endswith("니다"))):
            found.append(f"the narration {say!r}: the sentence {s!r} does not end in 니다. (the 합니다 style)")
    found += [f"the narration {say!r} holds {what}" for ch, what in BANNED.items() if ch in say]
    heard = spoken(say, READINGS.get(lang, {}))
    left = re.findall(r"[A-Za-z]+|[0-9]+", heard)                  # what the plugin's --hangul-only refuses
    if left:
        found.append(f"the narration {say!r} still holds {', '.join(map(repr, left))} after the readings (spoken: "
                     f"{heard!r}): give it a reading in READINGS[{lang!r}] or write it in Hangul")
    return found


def is_number(value) -> bool:
    """A finite number as a beat may give it, of seconds or of pixels (not a text, not true or false)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def frame_problems(box) -> list[str]:
    """A box given as numbers, [x, y, w, h] or a list of them, is four numbers with a size that lie inside FRAME, each
    rounded to a pixel first (the rule of the plugin's clip step, which finds it only once the script files are written
    and the clips before it are cut). A box from the camlog ('shot:<key>', 'mark:<key>') is left to the clip step."""
    if not isinstance(box, (list, tuple)) or not box:
        return []
    found = []
    for rect in box if isinstance(box[0], (list, tuple)) else [box]:
        if not (isinstance(rect, (list, tuple)) and len(rect) == 4 and all(is_number(v) for v in rect)):
            found.append(f"the box {rect!r} needs four numbers [x, y, w, h]")
            continue
        x, y, w, h = (round(v) for v in rect)
        if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > FRAME[0] or y + h > FRAME[1]:
            found.append(f"the box {list(rect)} has no size or lies outside the {FRAME[0]}x{FRAME[1]} frame")
    return found


def value_problems(b: dict) -> list[str]:
    """A caption's own values for the voiced build: "voice_at" a number; "ends_early" true or false, and true only on
    a narrated caption with "dur"; "box_delay" a number of 0 or more and "box_dur" a number above 0, each only beside
    a box; a box given as numbers inside the frame (frame_problems). Where the voice starts in its piece is checked
    once the pieces are split, see voiced_problems; where an early end falls, see early_end_problems."""
    found = []
    if "voice_at" in b and not is_number(b["voice_at"]):
        found.append(f'"voice_at" must be a number of seconds (it is {b["voice_at"]!r})')
    if "ends_early" in b and not isinstance(b["ends_early"], bool):
        found.append(f'"ends_early" must be true or false (it is {b["ends_early"]!r})')
    elif b.get("ends_early") and "dur" not in b:
        found.append('"ends_early" on a caption without "dur" (it ends the caption where its "dur" ended it)')
    elif b.get("ends_early") and "say" not in b:
        found.append('"ends_early" on a caption without a narration (only a narrated caption is held)')
    for field in ("box_delay", "box_dur", "what"):
        if field in b and not box_count(b.get("box")):
            found.append(f'"{field}" on a caption without a box')
    if box_count(b.get("box")):
        found += frame_problems(b["box"])
        if "box_delay" in b and not (is_number(b["box_delay"]) and b["box_delay"] >= 0):
            found.append(f'"box_delay" must be a number of seconds, 0 or more (it is {b["box_delay"]!r})')
        if "box_dur" in b and not (is_number(b["box_dur"]) and b["box_dur"] > 0):
            found.append(f'"box_dur" must be a number of seconds above 0 (it is {b["box_dur"]!r})')
    return found


def what_problems(b: dict) -> list[str]:
    """A caption's boxes each have a short phrase in "what" that says what the box points at (the review page shows it
    beside the box)."""
    n, what = box_count(b.get("box")), b.get("what")
    if n and not what:
        return ['a box without "what" (one short phrase per box saying what it points at)']
    if what is None or not n:
        return []                                                  # a "what" with no box: see value_problems
    if not isinstance(what, list) or not all(isinstance(w, str) and w.strip() for w in what):
        return ['"what" must be a list of short phrases, one per box']
    return [f'{n} box(es) but {len(what)} phrase(s) in "what" (one per box)'] if len(what) != n else []


def narration_problems(spec: dict, lang: str) -> list[str]:
    """Every narration and box of the spec against the rules of the voiced build, one line each, naming the card or
    the caption (its piece as the silent build names it, and its text)."""
    found, used = [], used_names(spec)
    for name, card in spec["cards"].get(lang, {}).items():
        if "say" in card:
            found += [f"{name}: {p}" for p in say_problems(card["say"], lang)]
            if name not in used:
                found.append(f"{name}: a narration on a card that no reel uses")
    for take, pieces in spec["clips"].items():
        for name, part in zip(piece_names(take, pieces), pieces):
            for b in part["beats"].get(lang, []):
                who = f"{name}: {b['text']!r}"
                found += [f"{who}: {p}" for p in value_problems(b) + what_problems(b)]
                if "say" in b:
                    found += [f"{who}: {p}" for p in say_problems(b["say"], lang)]
                    if take not in used:
                        found.append(f"{who}: a narration on a piece that no reel uses")
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


def take_seconds(path: Path) -> float:
    """The length of a raw take as ffprobe reads it (the camlog runs on a little after the video ends)."""
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         check=True, capture_output=True, text=True).stdout
    return float(out)


def window_problems(spec: dict, lang: str, raw: Path, takes: set[str]) -> list[str]:
    """Each piece of the given takes against its take, and each caption against the take's camlog: the window starts
    before it ends and ends inside the take; the anchor is there, it falls inside its piece with at least ROOM seconds
    of the finished piece after it, and an explicit "dur" ends before the next caption starts."""
    found, logs, lengths = [], {}, {}
    for take in sorted(takes):
        pieces = spec["clips"][take]
        for name, part in zip(piece_names(take, pieces), pieces):
            if not part["start"] < part["end"]:
                found.append(f"{name}: its window {part['start']}..{part['end']} does not start before it ends")
                continue
            if part["raw"] not in lengths:
                lengths[part["raw"]] = take_seconds(raw / f"{part['raw']}.webm")
            if part["end"] > lengths[part["raw"]] + 0.01:
                found.append(f"{name}: its window ends at {part['end']} s, beyond the take {part['raw']} "
                             f"({lengths[part['raw']]:.2f} s)")
            starts = []                                   # each caption's start in the finished piece, and its beat
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
                    continue
                starts.append(((t - part["start"]) / part["speed"], b))
            starts.sort(key=lambda x: x[0])
            for (t0, b), (t1, _) in zip(starts, starts[1:]):
                if "dur" in b and t0 + float(b["dur"]) > t1:
                    found.append(f"{name}: {b['text']!r} runs into the next caption (it ends at {t0 + float(b['dur']):.2f}"
                                 f" s of the piece, the next starts at {t1:.2f} s)")
    return found


# ---------------------------------------------------------------------------------------- the plugin's script files

def clip_script(part: dict, lang: str) -> dict:
    """edit_demo.py's script for a piece: no title (the chapter cards carry it), the window, the speed, the beats (with
    the fields of a silent caption only: a narration and its boxes stay out of the silent build)."""
    return {"start": part["start"], "end": part["end"], "speed": part["speed"],
            "beats": [{k: v for k, v in b.items() if k in SILENT_FIELDS} for b in part["beats"].get(lang, [])]}


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


def clip_command(plugin: Path, name: str, part: dict, lang: str, out: Path, folder: str | None = None) -> list[str]:
    """edit_demo.py clip for one piece, its script and clip in scripts/<folder>/ and clips/<folder>/ (the language's
    folder unless given). A piece with no beats is cut without captions: the plugin would otherwise burn the camera's
    shot labels, which are notes for the person who records."""
    folder = folder or lang
    cmd = [sys.executable, str(plugin / "edit_demo.py"), "clip", str(out / "raw" / f"{part['raw']}.webm"),
           "--script", str(out / "scripts" / folder / f"{name}.json"),
           "--out", str(out / "clips" / folder / f"{name}.mp4")]
    return cmd + ([] if part["beats"].get(lang) else ["--no-captions"])


# ------------------------------------------------------------------------------- the voiced build's script files

def voiced_script(part: dict, lang: str) -> dict:
    """edit_demo.py's script for a piece of the voiced build: as the silent one, plus each caption's boxes and their
    delay; a narrated caption is held to the clip's last frame, so that a frame the reel holds for its voice still
    shows the caption and its boxes (the piece holds one caption, see split_piece)."""
    beats = [{k: v for k, v in b.items() if k in VOICED_FIELDS} | ({"hold": True} if "say" in b else {})
             for b in part["beats"].get(lang, [])]
    return {"start": part["start"], "end": part["end"], "speed": part["speed"], "beats": beats}


def split_piece(part: dict, lang: str, log: list[dict]) -> list[dict]:
    """A piece as the voiced build cuts it, one caption per piece: a piece with several captions is cut before each
    later caption, SPLIT_LEAD seconds of the take before its anchor (with its offset); the first keeps the piece's
    start, the last its end, all its take and speed. `log` is the camlog of the piece's raw take."""
    beats = part["beats"].get(lang, [])
    if len(beats) < 2:
        return [copy.deepcopy(part)]
    timed = []
    for b in beats:
        t = anchor_seconds(b["at"], log)
        if t is None:
            raise SystemExit(f"{b['text']!r} is anchored to {b['at']!r}, which the camlog of {part['raw']} "
                             "does not hold")
        timed.append((t + float(b.get("offset", 0)), b))
    timed.sort(key=lambda x: x[0])
    cuts = [part["start"], *(round(t - SPLIT_LEAD, 3) for t, _ in timed[1:]), part["end"]]
    return [{**copy.deepcopy(part), "start": cuts[i], "end": cuts[i + 1], "beats": {lang: [copy.deepcopy(b)]}}
            for i, (_, b) in enumerate(timed)]


def early_end(b: dict, part: dict, log: list[dict]) -> float:
    """The take's second at which a caption ended in the silent video: its start plus its "dur" (at least
    CAPTION_LEAST) in the finished piece, turned back into seconds of the take."""
    return round(part["start"] + (caption_start(b, part, log) + max(float(b["dur"]), CAPTION_LEAST)) * part["speed"], 3)


def split_at_early_end(part: dict, lang: str, log: list[dict]) -> list[dict]:
    """A piece of one caption as the voiced build cuts it: when its caption has "ends_early" (and "dur"), the piece
    ends where the caption ended in the silent video, and the rest of its window becomes a piece without a caption
    (the same take and speed; the voice runs on over it). Any other piece comes back as it is."""
    said = [b for b in part["beats"].get(lang, []) if b.get("ends_early") is True and "dur" in b]
    if len(part["beats"].get(lang, [])) != 1 or not said:
        return [part]
    cut = early_end(said[0], part, log)
    if not part["start"] < cut < part["end"]:
        return [part]                                              # early_end_problems names it
    return [{**part, "end": cut}, {**copy.deepcopy(part), "start": cut, "beats": {lang: []}}]


def voiced(spec: dict, lang: str, logs: dict[str, list]) -> dict:
    """The spec as the voiced build cuts it: every piece with several captions split (split_piece), and every caption
    that ends early given a piece of its own up to its end (split_at_early_end), so that the pieces of a take are
    numbered anew; the cards and reels as they are. `logs`: the camlog of each raw take, by its name."""
    out = copy.deepcopy(spec)
    out["clips"] = {take: [p for part in pieces for p in _voiced_of(part, lang, logs)]
                    for take, pieces in spec["clips"].items()}
    return out


def _voiced_of(part: dict, lang: str, logs: dict[str, list]) -> list[dict]:
    """The voiced pieces that one piece of the spec becomes."""
    log = logs.get(part["raw"], [])
    return [q for p in split_piece(part, lang, log) for q in split_at_early_end(p, lang, log)]


def early_end_problems(spec: dict, lang: str, logs: dict[str, list]) -> list[str]:
    """A caption that ends early leaves ROOM seconds of its finished piece to itself and to the piece after it, and
    its box shows whole before the caption ends (a box shows from the caption's start plus its delay, the plugin's
    rule, for "box_dur" seconds or to the caption's end). One line each, naming the caption by its piece of the spec."""
    found = []
    for take, pieces in spec["clips"].items():
        for name, part in zip(piece_names(take, pieces), pieces):
            log = logs.get(part["raw"], [])
            for p in split_piece(part, lang, log):
                for b in p["beats"].get(lang, []):
                    if b.get("ends_early") is not True or "dur" not in b:
                        continue
                    who, cut = f'{name}: {b["text"]!r}: "ends_early"', early_end(b, p, log)
                    shows, rest = max(float(b["dur"]), CAPTION_LEAST), (p["end"] - cut) / p["speed"]
                    if shows < ROOM:
                        found.append(f"{who} shows the caption {shows:.2f} s, less than {ROOM} s (ROOM)")
                    if rest < ROOM:
                        found.append(f"{who} ends the caption at {cut} s of the take and leaves {rest:.2f} s of its "
                                     f"piece after the caption, less than {ROOM} s (ROOM)")
                    if not box_count(b.get("box")) or rest < ROOM:
                        continue
                    end = (cut - p["start"]) / p["speed"]          # the caption's end in its finished piece
                    begins = caption_start(b, p, log) + _box_delay(b, p["speed"])
                    if round(begins - end, 6) >= 0:
                        found.append(f"{who} ends the caption at {end:.2f} s of its piece, before its box would show "
                                     f"(from {begins:.2f} s)")
                    elif "box_dur" in b and round(begins + float(b["box_dur"]) - end, 6) > 0:
                        found.append(f'{who} ends the caption at {end:.2f} s of its piece, before its box ends at '
                                     f'{begins + float(b["box_dur"]):.2f} s: shorten "box_dur" to {end - begins:.2f} s '
                                     "or less")
    return found


def _box_delay(b: dict, speed: float) -> float:
    """Seconds after its caption starts that a box shows: "box_delay", or, the plugin's rule, the camera's arrival on a
    shot the caption is anchored to (CAMERA_MOVE / speed + 0.2), else 0."""
    if "box_delay" in b:
        return float(b["box_delay"])
    return CAMERA_MOVE / speed + 0.2 if str(b["at"]).startswith("shot:") else 0.0


def _narrated(spec: dict, lang: str):
    """(name, card or caption, piece or None) for every narration of a voiced spec: cards by their name, pieces by
    <take>.<n>."""
    for name, card in spec["cards"][lang].items():
        if "say" in card:
            yield name, card, None
    for name, part in _pieces(spec):
        said = [b for b in part["beats"].get(lang, []) if "say" in b]
        if len(said) > 1:
            raise ValueError(f"{name} holds {len(said)} narrations: split its captions first (voiced)")
        if said:
            yield name, said[0], part


def voice_lines(spec: dict, lang: str) -> dict[str, str]:
    """The plugin's lines.json for a voiced spec: each narration's name and its text as written (the voice step applies
    READINGS)."""
    return {name: item["say"] for name, item, _ in _narrated(spec, lang)}


def voice_starts(spec: dict, lang: str, logs: dict[str, list]) -> dict[str, float]:
    """Seconds into its segment that each narration of a voiced spec starts: a card's VOICE_DELAY; a caption's start in
    the finished piece, max(0, (anchor + offset - start) / speed), plus VOICE_DELAY, unless the beat gives "voice_at"."""
    def start(item: dict, part: dict | None) -> float:
        if part is None:
            return VOICE_DELAY
        if "voice_at" in item:
            return float(item["voice_at"])
        return round(caption_start(item, part, logs[part["raw"]]) + VOICE_DELAY, 3)
    return {name: start(item, part) for name, item, part in _narrated(spec, lang)}


def caption_start(b: dict, part: dict, log: list[dict]) -> float:
    """Seconds into its finished piece that a caption starts: max(0, (anchor + offset - start) / speed)."""
    return max(0.0, (anchor_seconds(b["at"], log) + float(b.get("offset", 0)) - part["start"]) / part["speed"])


def voiced_problems(spec: dict, lang: str, logs: dict[str, list]) -> list[str]:
    """A "voice_at" given on a caption of a voiced spec lies inside its piece and not before its caption starts (a
    voice never speaks of what is not on the screen yet), one line each, naming the voiced piece and the caption."""
    found = []
    for name, part in _pieces(spec):
        for b in part["beats"].get(lang, []):
            if "voice_at" not in b or not is_number(b["voice_at"]):
                continue                                           # a value that is no number: value_problems
            at, begins = b["voice_at"], round(caption_start(b, part, logs[part["raw"]]), 3)
            length = (part["end"] - part["start"]) / part["speed"]
            who = f'{name}: {b["text"]!r}: "voice_at" {at} s'
            if at < begins:
                found.append(f"{who} lies before its caption's start at {begins:.2f} s")
            elif at > length:
                found.append(f"{who} lies beyond its piece ({length:.2f} s long)")
    return found


def reel_texts(spec: dict, reel: str, lang: str) -> dict:
    """The review page's texts for the narrations of one reel of a voiced spec: the caption (a card's title), the
    narration as written, and what each box points at."""
    names = {n for s in spec["reels"][reel]
             for n in (piece_names(s, spec["clips"][s]) if s in spec["clips"] else [s])}
    return {name: {"caption": item["title"] if part is None else item["text"], "say": item["say"],
                   "what": list(item.get("what") or [])} for name, item, part in _narrated(spec, lang) if name in names}


def voiced_manifest(spec: dict, reel: str, lang: str, at: dict[str, float]) -> dict:
    """edit_demo.py's reel for a voiced spec, with the build's thresholds: a card is its picture for its seconds; the
    pieces of a take meet in hard cuts and share a group, so that a voice may run on over its take's later pieces
    without a caption, never into another take or a card; a piece with a caption and no narration has a group of its
    own, so that no voice runs on over it. A segment whose name is in `at` carries its voice, starting that many
    seconds into the segment."""
    def narrated(entry: dict, name: str) -> dict:
        return entry | ({"voice": f"voice/{lang}/{name}.mp3", "voice_at": at[name]} if name in at else {})
    segments = []
    for name in spec["reels"][reel]:
        if name not in spec["clips"]:
            segments.append(narrated({"image": f"cards/{lang}/{name}.png",
                                      "seconds": spec["cards"][lang][name]["seconds"]}, name))
            continue
        names = piece_names(name, spec["clips"][name])
        for i, (file, part) in enumerate(zip(names, spec["clips"][name])):
            beats = part["beats"].get(lang, [])
            unsaid = beats and not any("say" in b for b in beats)
            entry = {"file": f"clips/{lang}-voice/{file}.mp4", "group": file if unsaid else name}
            if i > 0:
                entry["fade_in"] = 0
            if i < len(names) - 1:
                entry["fade_out"] = 0
            segments.append(narrated(entry, file))
    return {"fade": 0.4, "voice_gap": VOICE_GAP, "voice_tail": VOICE_TAIL, "loudness": LOUDNESS, "segments": segments}


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
    used = used_names(spec) & set(spec["clips"])
    _need_raws(spec, used, out)
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


def run_voice(spec: dict, lang: str = "ko", out: Path = OUT, check_only: bool = False) -> None:
    """The narrated reels beside the silent ones. Every check comes before anything is written: the texts, the
    narrations and boxes, the raw takes, each caption in its piece and, once split, in its own piece, and where each
    given voice start lies in its piece. Then the script files, the lines, the readings and the review page's texts;
    without check_only the clips, any missing card and the voices; the manifests; without check_only, per reel: the
    reel, its audit (a failed one stops the build), the boxes of its pieces, its review page."""
    found = problems(spec, lang)
    if found:
        _stop(found, "text(s) break the rules; nothing was written")
    if lang not in VOICES:
        _stop([f"no voice for the language {lang!r} (there are: {', '.join(sorted(VOICES))})"],
              "language without a voice; nothing was written")
    found = narration_problems(spec, lang)
    if found:
        _stop(found, "narration(s) or box(es) break the rules; nothing was written")
    plugin = None if check_only else _plugin(("edit_demo.py", "make_cards.py", "check_demo.py"))
    used = used_names(spec) & set(spec["clips"])
    _need_raws(spec, used, out)
    found = window_problems(spec, lang, out / "raw", used)
    if found:
        _stop(found, "caption(s) do not sit in their pieces; nothing was written")
    logs = {r: json.loads((out / "raw" / f"{r}.camlog.json").read_text())["log"]
            for r in sorted({p["raw"] for t in used for p in spec["clips"][t]})}
    in_reels = {**spec, "clips": {t: pieces for t, pieces in spec["clips"].items() if t in used}}  # the spec's order
    found = early_end_problems(in_reels, lang, logs)
    if found:
        _stop(found, "caption(s) cannot end early as asked; nothing was written")
    v = voiced(in_reels, lang, logs)
    found = window_problems(v, lang, out / "raw", used)
    if found:
        _stop(found, "caption(s) do not sit in their own pieces once split (one caption per piece); nothing was written")
    found = voiced_problems(v, lang, logs)
    if found:
        _stop(found, "voice start(s) do not fit their pieces once split; nothing was written")

    scripts, voice = out / "scripts" / f"{lang}-voice", out / "voice" / lang
    for name, part in _pieces(v):
        write(scripts / f"{name}.json", voiced_script(part, lang))
    lines = voice_lines(v, lang)
    write(voice / "lines.json", lines)
    write(voice / "readings.json", READINGS.get(lang, {}))
    for reel in v["reels"]:
        write(_report(out, reel, lang) / "texts.json", reel_texts(v, reel, lang))
    if plugin:
        _clips_cards_and_voices(plugin, v, lang, out)
    at = voice_starts(v, lang, logs)
    for reel in v["reels"]:
        write(out / "reels" / f"{reel_file(reel, lang)}-voice.json", voiced_manifest(v, reel, lang, at))
    on_cards = sum(1 for n in lines if n in v["cards"][lang])
    print(f"checked (voice): {len(v['clips'])} takes in {len(_pieces(v))} pieces, one caption at most each "
          f"({sum(len(spec['clips'][t]) for t in v['clips'])} before the split), {len(lines)} narrations ({on_cards} on "
          f"cards, {len(lines) - on_cards} on captions), {len(v['reels'])} reels; files in {out}")
    for take in v["clips"]:
        for line in _renamed(spec["clips"][take], take, lang, logs):
            print(f"  {line}")
    if plugin:
        for reel in v["reels"]:
            _reel_and_checks(plugin, v, reel, lang, out)


def _clips_cards_and_voices(plugin: Path, v: dict, lang: str, out: Path) -> None:
    """The clips of a voiced spec, the card pictures the silent build has not made yet, then the plugin's voice step
    (only what changed is synthesized). The clips come first: a box the clip step refuses stops the build before
    anything is synthesized."""
    voice, py = out / "voice" / lang, sys.executable
    for name, part in _pieces(v):
        _step(clip_command(plugin, name, part, lang, out, folder=f"{lang}-voice"), f"the piece {name}")
    cards, used = v["cards"][lang], used_names(v)
    missing = [n for n in cards if n in used and not (out / "cards" / lang / f"{n}.png").exists()]
    if missing:
        write(voice / "cards.json", {n: {"seconds": cards[n]["seconds"], "lines": card_lines(cards[n])}
                                     for n in missing})
        _step([py, str(plugin / "make_cards.py"), str(voice / "cards.json"), "--out", str(out / "cards" / lang)],
              f"the card(s) {', '.join(missing)}")
    _step([py, str(plugin / "edit_demo.py"), "voice", str(voice / "lines.json"), "--out", str(voice),
           "--readings", str(voice / "readings.json"), "--hangul-only", *VOICES[lang]], "the narrations")


def _reel_and_checks(plugin: Path, v: dict, reel: str, lang: str, out: Path) -> None:
    """One narrated reel: the plugin's reel, its audit (a failed one stops the build with the report's lines), the
    boxes of each of its pieces that has one, and its review page."""
    py, check, report = sys.executable, str(plugin / "check_demo.py"), _report(out, reel, lang)
    manifest, mp4, plan = (out / "reels" / f"{reel_file(reel, lang)}-voice{ext}" for ext in (".json", ".mp4", ".voice.json"))
    _step([py, str(plugin / "edit_demo.py"), "reel", str(manifest), "--out", str(mp4)], f"the reel {reel}", cwd=out)
    (report / "audit.json").unlink(missing_ok=True)               # an audit that ends without a report shows no old one
    done = subprocess.run([py, check, "audit", str(mp4), "--plan", str(plan), f"--tolerance={VOICE_TOLERANCE}",
                           f"--loudness={LOUDNESS}", "--out", str(report / "audit.json")])
    if done.returncode != 0:
        _stop(_audit_lines(report / "audit.json", done.returncode),
              f"problem(s) in the audit of {mp4.name} (report: {report / 'audit.json'}); the build stopped there")
    boxed = [(name, part) for take in v["reels"][reel] if take in v["clips"]
             for name, part in zip(piece_names(take, v["clips"][take]), v["clips"][take])
             if any(box_count(b.get("box")) for b in part["beats"].get(lang, []))]
    for name, part in boxed:
        _step([py, check, "boxes", str(out / "scripts" / f"{lang}-voice" / f"{name}.json"), "--raw",
               str(out / "raw" / f"{part['raw']}.webm"), "--out", str(report / "boxes" / f"{name}.json")],
              f"the piece {name} of the reel {reel}")
    boxes = [str(report / "boxes" / f"{name}.json") for name, _ in boxed]
    _step([py, check, "sheet", str(mp4), "--plan", str(plan), "--texts", str(report / "texts.json"),
           *(["--boxes", *boxes] if boxes else []), "--out", str(report)], f"the reel {reel}")
    print(f"reel {reel}: {mp4}, audit passed, review page {report / 'review.html'}")


def _step(cmd: list[str], what: str, cwd: Path | None = None) -> None:
    """One plugin step of the voiced build (cmd: the Python, the plugin's script and its arguments). A step that fails
    has said why in its own lines; the build adds one naming the step and what it was run for, and stops (exit 2)."""
    done = subprocess.run(cmd, cwd=cwd)
    if done.returncode != 0:
        script = Path(cmd[1]).name
        step = script if script == "make_cards.py" else f"{script} {cmd[2]}"
        print(f"build stopped: {step} failed for {what} (exit {done.returncode})", file=sys.stderr)
        raise SystemExit(2)


def _report(out: Path, reel: str, lang: str) -> Path:
    """The folder of a narrated reel's checks and review page."""
    return out / "reports" / f"{reel}-{lang}-voice"


def _renamed(pieces: list[dict], take: str, lang: str, logs: dict[str, list]) -> list[str]:
    """How the split renames a take's pieces: one line per silent piece whose voiced name or names differ."""
    lines, n = [], 1
    for name, part in zip(piece_names(take, pieces), pieces):
        k, captions = len(_voiced_of(part, lang, logs)), len(part["beats"].get(lang, []))
        now = [f"{take}.{i}" for i in range(n, n + k)]
        why = [f"{captions} captions"] * (captions > 1) + ["a caption that ends early"] * (k > max(1, captions))
        if now != [name]:
            lines.append(f"{name} -> {', '.join(now)}" + (f" (split: {', '.join(why)})" if why else ""))
        n += k
    return lines


def _audit_lines(report: Path, code: int) -> list[str]:
    """The problems a failed audit wrote into its report (or why there is none)."""
    try:
        return [str(p) for p in json.loads(report.read_text(encoding="utf-8"))["problems"]] or \
            [f"the audit exited {code} and its report names no problem"]
    except (OSError, ValueError, KeyError, TypeError):
        return [f"the audit exited {code} and wrote no readable report at {report}"]


def _need_raws(spec: dict, used: set[str], out: Path) -> None:
    """Every raw take and camlog the used takes are cut from is under out/raw/, or the build stops (exit 1)."""
    missing = sorted({f"raw/{p['raw']}{ext}" for t in used for p in spec["clips"][t] for ext in (".webm", ".camlog.json")
                      if not (out / "raw" / f"{p['raw']}{ext}").exists()})
    if missing:
        print(f"no raw take for {', '.join(missing)} (under {out}): record it with demo_video/scenes/record.sh",
              file=sys.stderr)
        raise SystemExit(1)


def _stop(found: list[str], what: str) -> None:
    for line in found:
        print(line, file=sys.stderr)
    print(f"build stopped: {len(found)} {what}", file=sys.stderr)
    raise SystemExit(2)


def _plugin(needs: tuple[str, ...] = ("edit_demo.py", "make_cards.py")) -> Path:
    """The plugin's scripts folder (DEMO_VIDEO_PLUGIN) with the scripts a build needs, or the build stops (exit 2). A
    folder that lacks only check_demo.py is a plugin older than the narrated build needs (demo-video 1.4.0 adds it)."""
    import os
    folder = os.environ.get("DEMO_VIDEO_PLUGIN")
    missing = [f for f in needs if not folder or not (Path(folder) / f).is_file()]
    if missing == ["check_demo.py"]:
        print(f"DEMO_VIDEO_PLUGIN names a demo-video plugin without check_demo.py: the narrated build needs demo-video "
              f"1.4.0 or later (edit_demo.py voice, voices and pictures in a reel, check_demo.py): {PLUGIN_URL}",
              file=sys.stderr)
        raise SystemExit(2)
    if missing:
        print(f"DEMO_VIDEO_PLUGIN must name the scripts folder of the demo-video plugin ({', '.join(needs)}): "
              f"{PLUGIN_URL}", file=sys.stderr)
        raise SystemExit(2)
    return Path(folder)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="write the script files and check every text; cut nothing")
    ap.add_argument("--voice", action="store_true", help="the narrated reels, beside the silent ones")
    ap.add_argument("--lang", default="ko")
    ap.add_argument("--out", type=Path, default=OUT, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.voice:
        run_voice(SPEC, lang=a.lang, out=a.out.resolve(), check_only=a.check)
    else:
        run(SPEC, lang=a.lang, out=a.out.resolve(), check_only=a.check)


if __name__ == "__main__":
    main()
