# 시연 영상

허브의 시연 영상을 녹화하고 편집하는 데 쓰는 것을 모은 폴더입니다. 장면마다의 스토리보드(`scenes/`), 모든 자막과 해설이 든 편집 스크립트(`scripts/build.py`), 개발자 장면을 녹화하는 개발자 PC(`tools/dev_pc/`)가 있습니다. 영상, 녹화 원본, 개발자 PC의 홈과 자격 증명 파일은 `out/` 아래에 생기고 git에 올라가지 않습니다.

## 필요한 것

- 영상 플러그인 [demo-video](https://github.com/gonsoomoon-ml/claude-extensions/tree/main/plugins/demo-video). 이 폴더의 스크립트는 플러그인의 `scripts` 폴더를 환경 변수 `DEMO_VIDEO_PLUGIN`으로 찾습니다.
- 녹화하는 PC의 도구: Docker, jq, perl, AWS CLI, ttyd(1.6.3), Playwright를 둔 node(v22.18.0), ffmpeg와 ffprobe(4.4.2), Python 3과 Pillow, 한글 글꼴(NanumSquare). 괄호 안은 2026-11-23에 쓴 버전입니다.
- ttyd는 1.7부터 `-W` 없이 실행한 터미널이 입력을 받지 않습니다. 이 저장소의 스크립트는 `-W`를 주지 않으므로 1.7 이상에서는 장면이 터미널에 치지 못할 것입니다(해 보지 않았습니다).
- 올라와 있는 허브(`make deploy`). 녹화하는 사람의 자격 증명은 개발팀 역할을 맡을 수 있고(`sts:AssumeRole`) `sts:GetFederationToken`을 부를 수 있어야 합니다. `GetFederationToken`은 IAM 사용자의 장기 자격 증명으로만 부를 수 있습니다.

## 소리 없는 영상 (`scripts/build.py`)

영상의 글은 모두 `scripts/build.py`에 있습니다. 녹화 원본(`out/raw/<장면>.webm`)을 조각으로 자르고 자막과 카드를 넣어 릴 여섯을 만듭니다. 전체 릴 `hosting-hub-main-ko.mp4`와 그것을 단계마다 나눈 `hosting-hub-stage-<1..5>-ko.mp4`입니다.

```
python3 demo_video/scripts/build.py --check     # 글만 검사합니다. 릴마다 길이를 출력합니다
python3 demo_video/scripts/build.py             # 그다음 클립, 카드, 릴을 만듭니다
```

- 자막과 카드의 글은 45자 이하의 합니다체 한 문장이고, 단계마다 자막 수의 한도가 있습니다. 어긋난 글이 있으면 하나마다 한 줄로 말하고 아무것도 자르지 않습니다(종료 값 2).
- 누르고 치는 구간은 1.25배로, 기다리는 구간(심사, 경보, Claude Code가 일하는 동안)은 4배로 자릅니다. 프레임은 고치거나 합성하지 않습니다.
- `56-cause`에서는 원인을 말하는 답의 첫 줄이 화면 맨 위에 있는 0.8초만 0.13배로 느리게 틉니다.

## 해설이 든 영상 (`build.py --voice`)

같은 여섯 릴을 한국어 해설과 빨간 강조 상자를 넣어 따로 만듭니다. 이름 끝에 `-voice`가 붙고(`hosting-hub-main-ko-voice.mp4`), 소리 없는 릴은 그대로 둡니다. 해설이 든 전체 릴은 YouTube에 올렸습니다: <https://youtu.be/cp0YKgAmrxM>.

해설이 든 영상에는 demo-video 1.4.0 이상이 필요합니다(`edit_demo.py voice`, `check_demo.py`). 1.4.0은 2026-11-25에 공개되었습니다. `DEMO_VIDEO_PLUGIN`이 `check_demo.py`가 없는 폴더(1.3.0이 그렇습니다)를 가리키면 빌드는 한 줄로 말하고 멈춥니다(종료 값 2).

```
python3 demo_video/scripts/build.py --voice --check     # 해설과 상자를 검사합니다. AWS를 부르지 않습니다
AWS_REGION=<리전> python3 demo_video/scripts/build.py --voice     # 그다음 클립, 음성, 릴을 만들고 검사합니다
```

- 해설은 그 프레임에 보이는 것이나 이 저장소의 README에 적힌 것만 말합니다. 화면의 이름과 숫자는 `READINGS`의 읽는 법으로 바꿔 합성기에 보냅니다.
- 음성은 Amazon Polly(음성 `Seoyeon`, 엔진 `generative`, 언어 `ko-KR`)입니다. 해설 한 줄마다 `aws polly synthesize-speech`를 부르고, 글이 바뀌지 않은 줄은 다시 합성하지 않습니다.
- 빨간 상자(테두리 8px)는 허브 화면과 Claude Code의 화면에서 해설이 가리키는 곳에, 카메라가 멈춘 뒤 나타납니다. 개발자의 셸과 사용자의 셸에는 글자 줄 사이가 몇 px뿐이라 상자를 두지 않습니다.
- 소리는 해설뿐이고, 해설이 조각보다 길면 마지막 프레임을 해설이 끝날 때까지 그대로 보입니다. 모든 해설을 같은 만큼 키워 통합 음량 −16 LUFS에 맞추되 true peak는 −1.5 dBTP를 넘지 않게 합니다. 그것으로 모자라면 플러그인이 압축으로 맞추고, 그때는 해설끼리의 음량 차이가 바뀝니다(2026-11-24의 마지막 빌드는 압축하지 않았습니다).
- `--voice --check`는 소리 없는 `--check`와 달리 녹화 원본(`out/raw/`)을 읽습니다. 원본이 없는 새 checkout에서는 멈춥니다(종료 값 1).
- 해설이 든 빌드는 소리 없는 빌드가 그린 카드 그림을 그대로 씁니다. 카드의 글을 바꾸면 `build.py`를 `--check` 없이 먼저 돌립니다.

릴마다 플러그인의 `check_demo.py`가 셋을 봅니다.

| 검사 | 하는 일 |
|---|---|
| `audit` | 해설마다 소리가 계획한 자리(앞뒤 0.25초 안)에 있는지, 영상과 소리의 길이가 같은지, 통합 음량이 −16 LUFS에서 1.5 LU 안인지 봅니다. 어긋나면 빌드가 멈춥니다. |
| `boxes` | 상자가 글자나 선을 지나는지(`crosses`), 빨간 것 위에 있는지(`low_contrast`), 상자 안의 화면이 바뀌는지(`moved`) 재서 표시합니다. |
| `sheet` | 해설마다 프레임, 자막, 소리, 상자의 확대를 한 줄에 둔 확인 페이지 `review.html`을 씁니다. |

- 6초가 넘게 멈춘 프레임, 릴의 30 %가 넘는 멈춘 프레임, 14초가 넘는 해설, −16 LUFS에 닿지 못한 음량은 릴의 계획 파일(`.voice.json`의 `warnings`)에 경고로만 적힙니다.
- 한계: `audit`이 재는 것은 소리의 자리, 길이, 음량과 true peak뿐입니다. 해설의 말이 맞게 읽혔는지, 발음이 자연스러운지는 모릅니다.

## 만든 릴

소리 없는 릴은 2026-11-23에 만들고 2026-11-24에 자막의 낱말 아홉 개를 바꿔 다시 만들었습니다(길이는 같습니다). 해설이 든 릴은 2026-11-24에 만들었습니다. 모두 1920x1080, H.264, 30fps입니다. 멈춘 프레임과 통합 음량은 해설이 든 릴의 것입니다.

| 릴 | 소리 없는 릴 | 해설이 든 릴 | 멈춘 프레임 | 통합 음량 |
|---|---|---|---|---|
| 전체 | 10분 50초(649.7초) | 15분 16초(915.7초) | 29.0 % | −16.7 LUFS |
| 1단계(준비를 포함합니다) | 1분 39초 | 2분 57초 | 43.8 % | −16.4 LUFS |
| 2단계 | 2분 28초 | 3분 5초 | 20.3 % | −16.6 LUFS |
| 3단계 | 55초 | 1분 19초 | 29.7 % | −16.0 LUFS |
| 4단계 | 1분 56초 | 2분 46초 | 30.1 % | −16.0 LUFS |
| 5단계 | 3분 31초 | 4분 33초 | 22.6 % | −16.4 LUFS |

- 해설은 70개(카드 10, 자막 60)이고 상자는 29개입니다. 2026-11-24에 처음 합성한 글은 70줄 5,698자였습니다(리전 us-west-2).
- 여섯 릴 모두 `audit`을 통과했습니다. `boxes`는 상자 29개 어디에도 표시를 하지 않았고, 만든 사람이 확인 페이지에서 본 상자 29개는 모두 상자의 설명(`what`)이 말하는 것을 둘러쌌습니다.
- 남은 경고: 전체 릴에 6초가 넘게 멈춘 프레임이 여덟 곳 있고, 1단계와 4단계 릴은 멈춘 프레임이 릴의 30 %를 넘습니다. 네 릴(전체, 1단계, 2단계, 5단계)은 true peak 때문에 −16 LUFS에 0.4~0.7 LU 못 미칩니다.
- 만든 사람은 소리를 듣지 않았습니다. 확인한 것은 소리가 계획한 자리에 있다는 것(`audit`)과, 합성기에 보낸 글 70개가 해설에 `READINGS`를 적용한 것과 같다는 것입니다.
- `poster.png`는 전체 릴의 128.7초 프레임입니다.

## 녹화 (`scenes/`)

장면마다 폴더 하나에 `storyboard.mjs`가 있고, `scenes/record.sh`로 한 장면씩 녹화합니다. 스토리보드가 적은 화면이 답하지 않으면 `record.sh`는 실행할 명령을 말하고 멈춥니다.

```
export DEMO_VIDEO_PLUGIN=<플러그인의 scripts 폴더> PLAYWRIGHT_ROOT=<node_modules/playwright가 있는 폴더>
demo_video/scenes/record.sh <장면> [최대 초] [--lang ko]      # 예: record.sh 00-home, record.sh 21-review 720
```

| 화면 | 실행하는 명령 | 주소 |
|---|---|---|
| 허브 화면 | `make ui` | `127.0.0.1:8300` |
| 개발자 PC의 터미널 | `tools/dev_pc/run.sh term` | `127.0.0.1:7681` |
| 사용자의 셸 | `tools/user_shell.sh up` | `127.0.0.1:7682` |

- 스토리보드는 먼저 허브가 그 장면에 필요한 상태인지 봅니다(녹화하는 사람의 자격 증명으로 읽기만 합니다). 아니면 무엇이 다른지 한 줄로 말하고 아무것도 하지 않습니다.
- 녹화는 `out/raw/`에 영상, 카메라 기록, 화면의 글로 남습니다. 화면의 글에 12자리 숫자, 이메일 주소, AWS 액세스 키 ID의 모양이 있으면 그 줄을 가려 출력하고 종료 값 1로 끝납니다(`lib/check_texts.sh`).
- `REHEARSE=1`이면 허브 화면의 버튼을 누르지 않습니다.
- 심사를 기다리는 반복은 2026-11-23의 녹화 뒤에 `lib/hub.mjs`의 `waitForReview` 하나로 옮겼습니다. 옮긴 뒤의 네 스토리보드(`21-review`, `25-approved`, `52-incident`, `57-back`)는 돌려 보지 않았습니다.

장면이 치는 명령은 [`demo_scenes/README.md`](../demo_scenes/README.md)에 있습니다. 한 장면이 남긴 허브의 상태가 다음 장면의 시작이고, `00-home`은 `docs_adk`, `spec_assistant`, `parts-tools`가 승인되어 있고 `quality_agent`와 `release_review`가 없는 허브에서 시작합니다.

| 장면 | 하는 일 |
|---|---|
| `00-home` | 허브 화면의 홈 |
| `11-find` | Claude Code가 MCP 검색 도구로 부품 규격 도구를 찾고, 템플릿으로 `quality_agent`의 파일을 만듭니다(메모 `make_asked`부터 `12-make`) |
| `13-submit` | `release_review`와 `quality_agent`의 취약한 버전을 신청합니다 |
| `21-review` | 두 심사: `quality_agent`는 Scan에서 실패, `release_review`는 `APPROVED` |
| `22-works` | 사용자가 `release_review`를 부릅니다 |
| `23-reject` | 실패한 단계와 스캔이 찾은 줄을 보이고 반려합니다 |
| `24-again`, `25-approved` | 고친 버전을 신청하고, 그 심사가 `APPROVED` |
| `26-answers` | 사용자가 `quality_agent`를 부릅니다 |
| `31-logonly`, `32-passes`, `33-record` | 전사 정책 `guard_prompt`를 기록 모드로 겁니다. 숨은 지시가 든 요청이 지나고(200) 집계에 잡힙니다 |
| `41-enforce`, `42-blocked` | 적용 모드로 올리고, 같은 요청이 403 |
| `43-before`, `44-attach`, `45-after` | 커스텀 가드레일을 붙이기 전과 후. 붙인 채로 5단계까지 둡니다 |
| `51-usage` | 에이전트마다의 사용량, 도구마다의 호출, 도구 호출 경보 |
| `52-incident`, `53-alarm` | 도구를 반복해 부르는 버전(`v2-loop`)을 올리고, 경보가 `ALARM`이 됩니다 |
| `54-stop`, `55-neighbours` | `quality_agent`만 멈추고(403), 이웃은 답합니다(200) |
| `56-cause` | Claude Code가 로그(`logs`)와 코드를 읽고 원인을 찾습니다. 고치지 않습니다 |
| `57-back` | 고친 버전을 올리고, 승인된 뒤 재개하면 답합니다 |

- `13-submit`, `24-again`, `32-passes`, `52-incident` 뒤에는 곧바로 다음 장면을 녹화합니다.
- `13-submit`, `52-incident`, `57-back` 전에는 `run.sh agent quality_agent`로 리포의 `quality_agent`를 작업 폴더에 넣습니다. `57-back` 앞의 Claude Code 세션(`56-cause`)은 그 폴더에 쓸 수 있기 때문입니다.
- `57-back`이 올리기 전에 스스로 확인하는 것은 `agent.py`에 `asking again`이 없는지뿐입니다. 2026-11-23에는 `56-cause`와 `57-back` 사이에 그 명령을 돌린 기록이 없고, 그날 `56-cause`의 Claude Code는 파일을 고치지 않았다고 답했습니다.

### 사용자의 셸 (`tools/user_shell.sh`)

팀의 사용자가 에이전트를 부르는 터미널입니다. `user_shell.sh up`은 ttyd를 `127.0.0.1:7682`에서만 실행하고, 프롬프트는 `사용자 $ `입니다. 허브에는 사용자 역할이 따로 없어서 녹화하는 사람의 자격 증명으로 돕니다. 이 PC에서 그 주소에 닿는 것은 그 셸을 얻으므로, 녹화할 때만 실행하고 끝나면 `user_shell.sh down`으로 멈춥니다.

### Claude Code 장면

- 스토리보드(`lib/claude.mjs`)는 Claude Code가 묻는 말을 판단하지 않고, 어떤 물음에도 Yes를 고르지 않습니다. 묻는 창이 보이면 그 창을 카메라에 보이고 Esc(No)를 누른 뒤 장면이 정한 문장을 보냅니다.
- 글을 붙여 넣거나 Enter를 누르는 것은 바로 전에 본 화면에 묻는 창이 없을 때만 합니다. 그 사이에 창이 새로 뜨면 그 키는 그 창이 받습니다(녹화에서는 보지 못했습니다).
- 2026-11-23의 `11-find`는 묻는 말을 읽어 판단하던 앞선 스토리보드로 녹화해, 읽기만 하는 셸 명령 넷에 Yes를 골랐습니다. 지금의 스토리보드라면 다섯 물음 모두에 No입니다.
- `56-cause`의 Claude Code는 `variants/v2-loop/agent.py`를 읽고 원인을 답하면서, 횟수의 한도가 없어졌다는 그 파일의 주석("retry has lost its limit on the count")도 인용했습니다. 세 번 녹화해 두 번째를 쓰고, 세 번이 같은 홈에서 돌았지만 그 홈의 Claude Code 메모 폴더는 보지 않았습니다.

## 개발자 PC (`tools/dev_pc/`)

개발자 장면을 녹화하는 Docker 컨테이너입니다. 그 안에서 개발자가 Claude Code로 에이전트를 만들고, 카탈로그를 검색하고, 에이전트를 올리고, 로그를 봅니다. 사용자는 `dev`, 작업 폴더는 `/home/dev/work`, 프롬프트는 `개발자 $ `입니다.

| 이미지(`hub-dev-pc`)의 도구 | 버전 | 쓰는 곳 |
|---|---|---|
| Claude Code (`@anthropic-ai/claude-code`) | 2.1.330 | 코딩 도우미. Amazon Bedrock의 Claude로 돌고, Claude 계정으로 로그인하지 않습니다 |
| `mcp-proxy-for-aws` | 2.0.0 (`uv tool install mcp-proxy-for-aws==2.0.0`) | 카탈로그의 MCP endpoint에 SigV4로 서명해 Claude Code와 잇습니다 |
| Python, uv | 3.13, 0.10.8 | 장면 명령과 에이전트의 테스트 |
| AWS CLI | 2.31.10 | 컨테이너의 셸 |

### 컨테이너에 들어가는 자격 증명 둘

녹화하는 사람의 자격 증명은 컨테이너, 이미지, 마운트한 폴더 어디에도 들어가지 않습니다(`~/.aws`를 마운트하지 않습니다).

| 자격 증명 | 만드는 법 | 유효 시간 | 쓰는 것 |
|---|---|---|---|
| 개발팀 역할의 임시 자격 증명(`developer.ini`) | `sts:AssumeRole`, 세션 이름 `developer` | 1시간 | 컨테이너의 기본 AWS 프로필. 셸, 장면 명령, MCP 프록시, Claude Code가 실행하는 도구 |
| Claude Code의 Bedrock 토큰(`bedrock.json`) | `sts:GetFederationToken`, 이름 `hub-video-claude` | 4시간 | Claude Code 자신의 모델 호출(`awsCredentialExport`). 세션 정책 `bedrock-policy.json.tmpl`이 두 모델(Claude Sonnet 5.5, Claude Haiku 4.5)의 호출만 허락합니다 |

- 두 파일은 `demo_video/out/dev-pc/creds/`(폴더 700, 파일 600)에 있고, 컨테이너에는 읽기 전용(`/run/dev-pc`)으로 들어갑니다. `run.sh forget`과 `run.sh down`이 지웁니다.
- 한계: 토큰 파일은 컨테이너의 사용자가 읽을 수 있고, `Read(//run/dev-pc/**)`가 막는 것은 Claude Code의 파일 읽기 도구입니다. 셸의 다른 길까지 막는다고 보장하지 못하며, 그 토큰으로 할 수 있는 것은 두 모델의 호출뿐입니다.
- EC2 인스턴스에서는 컨테이너가 인스턴스 메타데이터 서비스에 닿을 수 있습니다. `run.sh up`은 `AWS_EC2_METADATA_DISABLED=true`를 주고, 실행 직후 root로 그 주소에 blackhole 경로를 한 번 넣습니다(`--cap-add NET_ADMIN`).
- 컨테이너는 `no-new-privileges`로 돕니다. `run.sh check`는 사용자 `dev`의 `CapEff`가 0이고 `dev`가 그 경로를 지우지 못하는 것을 보입니다.

### 이 PC와 컨테이너의 경계

- 컨테이너가 이 PC에 쓸 수 있는 곳은 자기 홈 `demo_video/out/dev-pc/home` 하나입니다. `run.sh`는 그 안의 것을 컨테이너 안에서(`docker exec`) 고치고, 홈이나 자격 증명 폴더가 심볼릭 링크면 거부합니다.
- 홈에는 컨테이너 안에서 쓴 파일(Claude Code의 메모와 대화 기록, `CLAUDE.md`)이 있습니다. 이 저장소를 이 PC에서 코딩 도우미로 열 때는 그 폴더를 읽지 않게 합니다(그곳의 `CLAUDE.md`를 지시로 받아들일 수 있습니다).
- 컨테이너는 Docker의 기본 bridge 네트워크에 있어 인터넷에 닿고, 이 PC가 모든 주소(`0.0.0.0`)에 연 포트에도 닿을 수 있습니다(해 보지 않았습니다). 허브 화면과 두 터미널은 loopback 주소에서만 듣습니다.

### `run.sh`

| 명령 | 하는 일 |
|---|---|
| `run.sh build` | 이미지 `hub-dev-pc`를 만듭니다. 이 PC의 파일은 이미지에 들어가지 않습니다. |
| `run.sh creds` | 자격 증명 둘을 만들어 파일로 둡니다. 두 주체와 끝나는 시각만 출력하고, 컨테이너가 떠 있는 동안 다시 돌려도 됩니다. |
| `run.sh up` | 컨테이너를 새로 실행하고 작업 폴더를 새로 만듭니다. 홈은 남습니다. |
| `run.sh check` | Claude Code가 Bedrock으로 답하는지, 인스턴스 메타데이터 서비스에 닿지 않는지, MCP 서버의 도구, 셸과 Claude Code가 개발팀 역할인지 봅니다. |
| `run.sh term` | ttyd를 `127.0.0.1:7681`에서만 실행합니다. |
| `run.sh agent <에이전트>` | 리포에서 git이 추적하는 `dev_team/<에이전트>`를 작업 폴더에 넣고, 있던 것은 `/home/dev/made-by-claude/`로 옮겨 둡니다. |
| `run.sh stop` | ttyd와 컨테이너를 멈춥니다. 홈은 남습니다. |
| `run.sh forget` | 자격 증명 파일 둘을 지웁니다. |
| `run.sh down` | `stop`과 `forget`. |

- 작업 폴더에는 리포에서 git이 추적하는 `dev_team/`, `platform_team/`, `demo_scenes/`, `pyproject.toml`, `uv.lock`과 이 폴더의 `CLAUDE.md`, `.mcp.json`, `.claude/settings.json`이 들어가고, Terraform 상태, `build/`, `.env`는 넣지 않습니다. `dev_team/quality_agent`도 없습니다(영상에서 Claude Code가 만듭니다).
- 새 홈에서는 녹화하기 전에 `run.sh term`의 터미널에서 `claude`를 한 번 실행해 처음에만 나오는 화면 넷에 손으로 답합니다. 답하지 않으면 스토리보드가 그 화면에 요청을 붙여 넣을 것입니다(코드와 그날의 화면으로 본 것이고, 해 보지 않았습니다). `run.sh check`의 `claude -p`는 이 폴더를 믿는다고 답하기 전에 `permissions.allow`를 무시했습니다(2026-11-23).

### Claude Code가 묻지 않고 하는 일

`settings.json`의 `permissions.allow`에 있는 것뿐입니다.

| 규칙 | 묻지 않고 하는 일 |
|---|---|
| `mcp__hub-catalog__*` | 카탈로그 MCP 서버의 도구(검색과 레코드 읽기) |
| `Edit(./dev_team/**)` | `dev_team/` 아래의 파일 쓰기와 고치기 |
| `Bash(search:*)`, `Bash(logs:*)` | 카탈로그 검색, 에이전트의 로그 보기([`demo_scenes/README.md`](../demo_scenes/README.md)) |
| `Bash(ls:*)`, `Bash(cat:*)` | 작업 폴더의 목록과 파일 보기 |

`permissions.deny`에 있는 것은 묻지 않고 거부합니다.

| 규칙 | 까닭 |
|---|---|
| `Read(//run/dev-pc/**)` | 자격 증명 파일 |
| `Edit(./demo_scenes/**)`, `Edit(./platform_team/**)`, `Edit(./pyproject.toml)`, `Edit(./uv.lock)` | 묻지 않고 도는 명령과, 그 명령이 부르는 코드와 Python 환경 |
| `Edit(./.claude/**)`, `Edit(./.mcp.json)` | Claude Code 자신의 설정과 MCP 서버 |
| `Edit(./dev_team/.claude/**)`, `Edit(./dev_team/.mcp.json)`, `Edit(./dev_team/CLAUDE.md)`, `Edit(./dev_team/**/.claude/**)`, `Edit(./dev_team/**/.mcp.json)`, `Edit(./dev_team/**/CLAUDE.md)` | 다음 세션이 읽을 Claude Code의 폴더, MCP 서버 목록, 지시 파일을 `dev_team/` 아래에 만들지 못하게 합니다 |
| `Edit(~/.claude/**)`, `Edit(~/.claude.json)` | 홈에 있는 Claude Code 자신의 파일. 홈은 `run.sh up` 뒤에도 남습니다 |

- 설정은 묻는 모드를 정하고(`"defaultMode": "default"`) auto mode를 끕니다(`"disableAutoMode": "disable"`). Claude Code 2.1.330은 따로 정하지 않으면 auto mode로 시작합니다.
- 그 밖의 도구는 Claude Code가 묻습니다(`publish`와 `uv run pytest`도). 장면 명령은 Python을 `-I`(격리 모드)로 실행해, 부른 폴더의 파일을 모듈로 불러오지 않습니다.
- 권한을 건너뛰는 모드나 플래그는 쓰지 않습니다. `run.sh check`만 한 명령(`aws sts get-caller-identity`)에 `--allowedTools`를 줍니다.
- 한계: `Bash(ls:*)`와 `Bash(cat:*)`는 경로나 리다이렉트(`>`)를 정하지 않습니다. 리다이렉트가 붙은 `cat`과 작업 폴더 밖을 보는 `ls`나 `cat`은 해 보지 않았습니다.
- 한계: 셸에서 `cd dev_team`을 한 뒤에는 `Edit(./dev_team/**)`이 맞지 않아 Claude Code가 묻습니다. 거부 규칙은 `cd` 뒤에도 맞았습니다(2026-11-23).
- `dev_team/` 바로 아래의 거부 셋과 홈의 거부 둘은 녹화(2026-11-23) 뒤에 더했고, 컨테이너에서 해 보지 않았습니다.

### 2026-11-23에 확인한 것

- `run.sh check`는 모두 통과했습니다. `claude -p`는 Bedrock 토큰으로 답했고, 인스턴스 메타데이터 서비스는 답하지 않았습니다.
- Claude Code의 화면 머리에는 조직, 이메일, 계정이 나오지 않았습니다.
- `aws sts get-caller-identity`는 셸에서도 Claude Code의 셸 도구에서도 `assumed-role/hub-dev-role/developer`였습니다. 토큰은 Claude Code의 모델 호출에만 쓰였습니다.
- `demo_scenes/search`를 고치는 것과 `dev_team/x/.claude/skills/y/SKILL.md`를 쓰는 것은 `File is in a directory that is denied by your permission settings.`로 거부되었습니다.
- 물을 때의 선택지에 auto mode로 바꾸는 것은 없었고, `Shift+Tab`은 manual, accept edits, plan 사이만 돌았습니다.
- Claude Code는 `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`인데도 처음 실행할 때 공식 플러그인 마켓플레이스(`anthropics/claude-plugins-official`, GitHub)를 등록했습니다. 설치된 플러그인은 없었습니다.
- 컨테이너에는 `python3` 명령이 없어서, 에이전트의 파일을 만든 Claude Code는 만든 코드의 문법을 확인하지 못했다고 말했습니다.
