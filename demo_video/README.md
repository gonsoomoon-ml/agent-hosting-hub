# 시연 영상

허브의 시연 영상을 만드는 데 쓰는 것을 모은 폴더다. 영상의 결과물과 녹화의 원본, 개발자 PC의 홈과 자격 증명 파일은 `out/` 아래에 생기고 git에 올라가지 않는다(`.gitignore`).

녹화와 편집은 영상 플러그인 [demo-video](https://github.com/gonsoomoon-ml/claude-extensions/tree/main/plugins/demo-video)의 스크립트(`record_demo.mjs`, `term.mjs`, `edit_demo.py`, `make_cards.py`)로 한다. 이 폴더의 스크립트는 그 플러그인의 `scripts` 폴더를 환경 변수 `DEMO_VIDEO_PLUGIN`으로 찾고, 없으면 그렇게 말하고 멈춘다.

## 영상 한 벌 (`scripts/build.py`)

영상의 글은 모두 이 파일 하나에 언어별로 있다: 클립마다 녹화 원본(`out/raw/<장면>.webm`), 속도, 쓰는 구간, 자막. 그리고 카드(처음, 장마다, 비교, 정리, 마무리)와 릴 여섯(`hosting-hub-main-ko.mp4`, `hosting-hub-stage-<1..5>-ko.mp4`).

```
python3 demo_video/scripts/build.py --check     # 플러그인의 스크립트 파일을 쓰고 글만 검사한다
python3 demo_video/scripts/build.py             # 그다음 클립, 카드, 릴을 만든다 (make_cards.py에 Pillow가 필요하다)
```

무엇을 쓰기 전에 모든 글을 플러그인의 자막 규칙으로 검사하고, 어긋난 글이 하나라도 있으면 글마다 한 줄로 말하고 멈춘다(종료 값 2). 규칙은 이렇다. 45자 이하, em dash, 가운뎃점, 화살표(U+2014, U+00B7, U+2192)를 쓰지 않는다, 속도 표시나 녹화에 대한 말을 쓰지 않는다. 자막, 장의 제목, 카드의 줄은 합니다체 한 문장이다(`니다`로 끝난다). 단계마다 자막 수의 한도(준비 5, 1단계 11, 2단계 12, 3단계 8, 4단계 10, 5단계 18)를 넘지 않는다. 릴은 이 파일이 정한 클립과 카드만 쓴다. 자막이 없는 클립은 자막 없이 자른다(플러그인은 자막이 없으면 카메라의 샷 이름을 대신 넣는데, 그것은 녹화하는 사람의 메모다).

## 녹화 (`scenes/`)

장면마다 폴더 하나에 `storyboard.mjs`(플러그인의 `record_demo.mjs`가 부르는 함수)가 있고, 녹화는 `scenes/record.sh`로 한다.

```
export DEMO_VIDEO_PLUGIN=<플러그인의 scripts 폴더> PLAYWRIGHT_ROOT=<node_modules/playwright가 있는 폴더>
demo_video/scenes/record.sh <장면> [최대 초] [--lang ko]      # 예: record.sh 00-home, record.sh 21-review 720
```

- 스토리보드는 찍는 화면을 한 줄(`export const surfaces = ['hub'];`)로 적는다. `hub`는 허브 화면(`make ui`, `127.0.0.1:8300`), `dev`는 개발자 PC의 터미널(`tools/dev_pc/run.sh term`, `127.0.0.1:7681`), `user`는 사용자의 셸(`tools/user_shell.sh up`, `127.0.0.1:7682`)이다. `record.sh`는 그 화면이 답하지 않으면 띄우는 명령을 말하고 멈춘다.
- 녹화는 `out/raw/<장면>.webm`, 카메라 기록 `out/raw/<장면>.camlog.json`, 화면의 글 `out/raw/<장면>.texts.txt`로 남는다. 화면의 글은 샷마다 하나이고, Claude Code 장면에서는 스토리보드가 샷 사이에 읽은 화면도 처음 본 것마다 하나씩 들어간다. 같은 장면을 다시 찍으면 앞의 것은 `out/raw/old/`로 옮긴다. 끝나면 샷, 메모, 선택자가 아무것도 찾지 못한 샷을 찍고, 화면의 글에 12자리 숫자나 이메일 주소가 있으면 그 줄을 (숫자는 가리고) 찍고 종료 값 1로 끝난다(`lib/check_texts.sh`. 개발자 PC의 이름 `dev@dev-pc`는 가리고 그 줄의 나머지도 검사한다).
- 스토리보드는 먼저 허브가 그 장면에 필요한 상태인지 본다(`lib/state.mjs`가 `lib/hub_state.py`로 카탈로그의 record와 상태, 도는 심사, 전사 정책의 모드, 커스텀 가드레일, 멈춘 에이전트를 읽는다. 녹화하는 사람의 자격 증명으로 읽기만 한다). 아니면 무엇이 다른지 한 줄로 말하고 아무것도 하지 않는다.
- 장면이 치거나 기다리는 글은 모두 `lib/texts.mjs`에 언어별로 있다. 스토리보드는 `--lang`을 읽는다. 지금은 한국어만 찍는다.
- 허브 화면의 버튼은 폼 POST이고 303으로 페이지를 다시 연다. 작업이 끝나면 페이지가 한 번 새로 읽힌다. 카메라는 페이지 안에 있으므로 `lib/hub.mjs`가 새 페이지마다 카메라를 다시 넣는다.

장면과 그 장면이 필요로 하는 허브의 상태다(스토리보드가 맨 먼저 확인한다). 한 장면이 남긴 상태가 다음 장면의 시작이다.

| 장면 | 화면 | 하는 일 | 필요한 상태 | 남기는 상태 |
|---|---|---|---|---|
| `00-home` | 허브 화면 | 홈: 수, 두 흐름의 그림, 플랫폼 구성, 카탈로그 | `docs_adk`, `spec_assistant`, `parts-tools` 승인, `quality_agent`와 `release_review` 없음, 전사 정책 꺼짐, 가드레일 떨어짐 | 바꾸지 않는다 |
| `11-find` | 개발자 PC | 한 Claude Code 세션: 카탈로그의 MCP 검색 도구로 부품 규격 도구를 찾고(`11-find`), 표준 템플릿으로 `quality_agent`의 파일을 만든다(메모 `make_asked`부터 `12-make`). 실행하거나 올리지 않는다 | `parts-tools` 승인, 두 에이전트 없음 | 컨테이너의 `dev_team/quality_agent`(Claude Code가 만든 것). 다음 장면 전에 `run.sh agent quality_agent` |
| `13-submit` | 개발자 PC | `publish release_review`, `publish quality_agent v1-vulnerable` | 두 에이전트 없음, 작업 폴더에 리포의 `quality_agent` | 두 record 승인 대기, 심사 둘이 돈다. 곧바로 `21-review`를 찍는다 |
| `21-review` | 허브 화면 | 두 심사를 처음부터 끝까지: `quality_agent`는 Scan에서 실패, `release_review`는 일곱 단계를 지나 `APPROVED` | 두 record 승인 대기, `release_review`의 심사가 돈다 | `release_review` 승인, `quality_agent` 승인 대기(실패한 심사) |
| `22-works` | 사용자의 셸 | `ask release_review --file demo_scenes/inputs/change-ok.txt` | `release_review` 승인 | 바꾸지 않는다 |
| `23-reject` | 허브 화면 | 실패한 단계, 스캔이 찾은 줄, 사유를 적고 반려(`REHEARSE=1`이면 누르지 않는다) | `quality_agent` 승인 대기, 도는 심사 없음 | `quality_agent` 반려 |
| `24-again` | 개발자 PC | 고친 판의 의존성을 보이고 `publish quality_agent` | `quality_agent` 반려 | 승인 대기, 심사가 돈다. 곧바로 `25-approved`를 찍는다 |
| `25-approved` | 허브 화면 | 고친 판의 심사가 일곱 단계를 지나 `APPROVED` | `quality_agent`의 심사가 돈다 | `quality_agent` 승인 |
| `26-answers` | 사용자의 셸 | `ask quality_agent "What is the spec of part P-100?"` | `quality_agent` 승인 | 바꾸지 않는다 |

### 사용자의 셸 (`tools/user_shell.sh`)

팀의 사용자가 호스팅된 에이전트를 부르는 터미널이다. `user_shell.sh up`은 ttyd를 `127.0.0.1:7682`에서만(`-i lo`, 다른 출처의 연결은 받지 않는다 `-O`) 띄우고, 페이지를 열 때마다 bash가 새로 뜬다. 프롬프트는 `사용자 $ `, 시작 폴더는 리포의 루트, PATH의 맨 뒤에 `demo_scenes/`가 있어서 `ask …`로 친다. rc 파일을 읽지 않고 기록(history)을 남기지 않는다. 허브에는 사용자 역할이 따로 없다(사용자는 에이전트 게이트웨이를 부를 수 있는 IAM 주체다). 그래서 이 셸은 녹화하는 사람의 자격 증명으로 돈다. 이 PC에서 `127.0.0.1:7682`에 닿는 것은 그 셸을 얻으므로 녹화할 때만 띄우고 끝나면 `user_shell.sh down`으로 멈춘다.

### Claude Code 장면

Claude Code가 화면에 찍는 것은 믿지 않는다. 묻는 말의 글(셸 명령, 파일 경로)은 다른 에이전트가 정하므로 스토리보드(`lib/claude.mjs`)는 그것을 판단하지 않고, 어떤 물음에도 Yes를 고르지 않는다. 스토리보드는 화면을 보고 언제 넘어갈지와 카메라를 어디에 둘지만 정한다. Claude Code가 물으면(묻는 줄 바로 아래에 선택지 `1. …`가 있으면) 그 창을 잡아 카메라에 보이고, Esc(No)를 누르고, 장면이 정한 문장(어떻게 계속할지)을 보낸다. 묻는 창이 화면에 있는 동안 누르는 키는 Esc뿐이다. Enter는 붙여 넣은 요청을 보낼 때만 누르고, 그 전에 화면을 보아 선택지처럼 보이는 줄(`1. Yes`, `2. No` 같은 줄)이 어디에도 없을 때만 누른다. 그런 줄이 있으면 Esc를 누르고 다시 보고, 그래도 있으면 한 줄로 말하고 장면을 멈춘다. 그래서 Claude Code는 파일을 셸 명령이 아니라 자기 쓰기 도구로 만들고(작업 폴더의 맨 위에 선 셸에서는 `dev_team/` 아래 쓰기를 묻지 않는다), 읽기는 자기 읽기 도구와 묻지 않고 허락된 `search`, `logs`, `ls`, `cat`으로 한다.

2026-11-23의 `11-find`는 이 스토리보드의 앞선 꼴로 찍었다. 그 꼴은 묻는 말의 글을 읽어 판단했고, 그 장면에서 읽기만 하는 셸 명령 넷(`cd`, `ls`, `cat`, `grep`, `sed -n`, `head`, `tail`, `for` 문 안의 `echo`와 `cat`)에 Yes, 앞의 43줄이 가려진 명령(폴더를 만들고 here-document로 파일을 쓰는 것)에 No를 골랐다. 그 꼴은 Claude Code가 그리는 창에서 코드를 돌리거나 파일을 쓰는 명령에도 Yes를 할 수 있었다(검토에서 그런 명령이 여럿 나왔다). 지금의 스토리보드라면 다섯 물음 모두에 No다.

2026-11-23의 녹화(`11-find`, UTC 11:50~12:07, 다섯 번 찍었다)에서 본 것이다. 첫 번째에는 "그 도구의 record를 보여 주세요"라는 요청에 Claude Code가 record의 ARN(계정 ID가 들어 있다)을 표로 보였고, `record.sh`의 글 검사가 그것을 잡아 그 녹화를 버렸다. 그 뒤로 요청은 도구의 이름, 설명, 입력을 묻는다. 그다음 세 번은 스토리보드가 묻는 말에 잘못 No를 고른 것(따옴표 안의 `|aws`를 명령으로 읽은 것, 긴 미리보기로 경로가 화면 밖에 있던 파일, 두 줄로 접힌 `cp` 명령)이어서 고치고 다시 찍었다. 다섯 번째에서 Claude Code는 읽기 넷을 묻고(Yes), 앞의 43줄이 화면에 보이지 않는 긴 명령(`mkdir`, `cp`, here-document로 파일 쓰기)을 물었고(No), 그 뒤 파일 다섯을 `dev_team/quality_agent/`에 묻지 않고 썼다. 아무것도 실행하거나 올리지 않았다.

같은 날 Claude Code가 셸에서 `cd dev_team`을 한 뒤에는 `dev_team/` 아래의 파일을 만들 때도 물었고, 화면의 경로는 `dev_team/`을 기준으로 보였다(`quality_agent/agent.json`). 12:54~12:56(UTC)에 컨테이너의 대화형 세션에서 확인했다. `cd demo_scenes` 뒤에 편집 도구로 `search`를 고치는 것과, `cd dev_team` 뒤에 `dev_team/x/.claude/skills/y/SKILL.md`를 쓰는 것은 둘 다 `File is in a directory that is denied by your permission settings.`로 거부되었다. 거부 규칙은 `cd` 뒤에도 맞았다. `dev_team/quality_agent/` 아래에 쓰는 것은 `cd` 없이는 묻지 않았고(파일이 생겼다), `cd dev_team` 뒤에는 절대 경로로 써도, 상대 경로로 써도 물었다(No로 답해서 생기지 않았다). 그러니 `cd` 뒤에 맞지 않게 되는 것은 허락 규칙 `Edit(./dev_team/**)`이고, 그때 Claude Code는 거부하지 않고 묻는다. 설정은 그대로 두었다. Claude Code는 `cd`만 있는 셸 명령은 묻지 않고 돌렸다.

## 개발자 PC (`tools/dev_pc/`)

개발자 장면을 찍는 PC다. Docker 컨테이너 하나이고, 이 안에서 개발자가 Claude Code로 에이전트를 만들고, 카탈로그를 검색하고, 에이전트를 올리고, 로그를 본다. 사용자는 `dev`, 호스트 이름은 `dev-pc`, 작업 폴더는 `/home/dev/work`, 프롬프트는 `개발자 $ `다.

이미지(`hub-dev-pc`)에 든 것과 버전이다. 모두 `Dockerfile`에 고정되어 있다.

| 도구 | 버전 | 쓰는 곳 |
|---|---|---|
| Claude Code (`@anthropic-ai/claude-code`) | 2.1.330 | 개발자의 코딩 도우미. Amazon Bedrock의 Claude로 돈다. Claude 계정으로 로그인하지 않는다. |
| `mcp-proxy-for-aws` | 2.0.0 (`uv tool install mcp-proxy-for-aws==2.0.0`) | 카탈로그(AWS Agent Registry)의 MCP endpoint에 SigV4로 서명해 Claude Code와 잇는다. |
| Python, uv | 3.13, 0.10.8 | 장면 명령(`search`, `publish`, `logs`)과 에이전트의 시험 |
| AWS CLI | 2.31.10 | 컨테이너의 셸 |

이 PC를 쓰려면 녹화하는 PC에 Docker, ttyd, jq, AWS CLI가 있고, 허브가 올라와 있고(`make deploy`), 녹화하는 사람의 AWS 자격 증명이 개발팀 역할을 맡을 수 있고(`sts:AssumeRole`) `sts:GetFederationToken`을 부를 수 있어야 한다. `GetFederationToken`은 IAM 사용자의 장기 자격 증명으로만 부를 수 있다.

### 컨테이너에 들어가는 자격 증명 둘

컨테이너에는 아래 둘만 들어간다. 녹화하는 사람의 자격 증명은 컨테이너, 이미지, 마운트한 폴더 어디에도 들어가지 않는다(`~/.aws`를 마운트하지 않는다).

| 자격 증명 | 만드는 법 | 유효 시간 | 쓰는 것 |
|---|---|---|---|
| 개발팀 역할의 임시 자격 증명(`developer.ini`) | `sts:AssumeRole`, 세션 이름 `developer` | 1시간(역할의 기본값) | 컨테이너의 기본 AWS 프로필. 셸, 장면 명령, MCP 프록시, Claude Code가 띄우는 도구가 모두 이것으로 돈다. |
| Claude Code의 Bedrock 토큰(`bedrock.json`) | `sts:GetFederationToken`, 이름 `hub-video-claude`, 세션 정책 `bedrock-policy.json.tmpl` | 4시간 | Claude Code 자신의 모델 호출. 설정 키 `awsCredentialExport`로 읽는다. 세션 정책은 영상의 두 모델(Claude Sonnet 5.5, Claude Haiku 4.5)의 추론 프로파일과 그 프로파일이 보내는 foundation model에 `bedrock:InvokeModel`과 `bedrock:InvokeModelWithResponseStream`만 허락한다. |

- 두 파일은 `demo_video/out/dev-pc/creds/`(폴더 700, 파일 600)에만 있고, 컨테이너에는 읽기 전용(`/run/dev-pc`)으로 들어간다. `run.sh creds`는 두 주체(계정은 `<ACCOUNT>`로 가린다)와 끝나는 시각만 찍고 키, 비밀 값, 토큰은 찍지 않는다. `run.sh forget`과 `run.sh down`이 두 파일을 지운다.
- 개발팀 역할에는 Bedrock 권한이 없고, Bedrock 토큰에는 모델 호출 말고는 권한이 없다.
- 한계: Bedrock 토큰 파일은 컨테이너의 사용자(Claude Code의 도구와 같은 사용자)가 읽을 수 있는 파일이다. `settings.json`의 `deny`(`Read(//run/dev-pc/**)`)가 Claude Code의 파일 읽기 도구를 막는다. 같은 모양의 `deny`는 묻지 않고 허락한 `cat`으로 그 파일을 읽는 셸 명령도 거부했다(2026-11-23, `/etc/hostname`을 막고 시험했다. 자격 증명 폴더로는 시험하지 않았다). 그래도 셸의 다른 길로 읽는 것까지 막는다고 보장하지는 못한다. 그 토큰으로 할 수 있는 것은 두 모델의 호출뿐이다.
- EC2 인스턴스에서는 컨테이너가 인스턴스 메타데이터 서비스에 닿을 수 있다(2026-11-23에 이 컨테이너를 돌린 EC2 인스턴스에서 닿았고, 그 인스턴스에는 역할이 있었다). `run.sh up`은 SDK가 그곳을 묻지 않게 하고(`AWS_EC2_METADATA_DISABLED=true`), 그 주소를 컨테이너의 네트워크에서 막는다. 막는 것은 root가 컨테이너를 띄운 직후 한 번 넣는 blackhole 경로다(`--cap-add NET_ADMIN`은 그 한 번을 위한 것이다). 컨테이너는 `no-new-privileges`로 돌아서 어느 프로세스도 권한을 더 얻지 못한다. 경로를 넣지 못하면 `up`은 컨테이너를 지우고 실패하고, `term`과 `check`는 경로가 없는 컨테이너를 거부한다. `run.sh check`는 사용자 `dev`의 `CapEff`가 0이고 `dev`가 그 경로를 지우지 못하는지(`Operation not permitted`) 보인다.

### 이 PC와 컨테이너의 경계

컨테이너가 이 PC에 쓸 수 있는 곳은 자기 홈 하나, `demo_video/out/dev-pc/home`(컨테이너의 `/home/dev`)이다. 자격 증명 폴더는 읽기 전용으로 들어간다. 홈 안에는 컨테이너 안의 어느 프로세스든 무엇이든 만들 수 있으므로(이 PC의 다른 폴더를 가리키는 심볼릭 링크도), `run.sh`는 홈 폴더를 만든 뒤로는 그 안의 것을 이 PC의 명령으로 만들거나 고치거나 지우지 않는다. 작업 폴더를 비우는 일, checkout을 넣는 일(이 PC가 표준 입력으로 보내는 tar), 설정 파일을 쓰는 일, `agent`가 에이전트를 바꿔 넣는 일은 모두 컨테이너 안에서 사용자 `dev`로(`docker exec`) 한다. 그곳에서는 링크가 컨테이너 안에서 풀리므로 이 PC의 다른 폴더에 닿지 않는다. `demo_video/out/dev-pc`, 홈, 자격 증명 폴더 자체가 심볼릭 링크면 `run.sh`는 한 줄로 거부한다. 홈(`demo_video/out/dev-pc/home/`)에는 컨테이너 안에서 쓴 파일(Claude Code의 메모와 대화 기록, 작업 폴더의 `CLAUDE.md`)이 있다. 이 저장소를 이 PC에서 코딩 도우미로 열 때는 도우미가 그 폴더를 읽지 않게 한다. 그런 도구는 그곳에서 찾은 `CLAUDE.md`를 지시로 받아들일 수 있다. 그 폴더에서 볼 것은 `docker exec`로 읽는다.

### `run.sh`

| 명령 | 하는 일 |
|---|---|
| `run.sh build` | 이미지 `hub-dev-pc`를 만든다. build context 없이 만들므로 이 PC의 파일은 이미지에 들어가지 않는다. |
| `run.sh creds` | 자격 증명 둘을 만들어 파일로 둔다. 컨테이너가 떠 있는 동안 다시 돌려도 된다(파일을 바꿔 두면 컨테이너는 다음 명령부터 새 것을 읽는다). |
| `run.sh up` | 컨테이너를 새로 띄우고 blackhole 경로를 넣는다. 그다음 컨테이너 안에서 작업 폴더를 새로 만들고(아래), `.mcp.json`을 허브의 카탈로그 ID로 채우고, `uv sync`를 한 번 돌린다. 홈(`demo_video/out/dev-pc/home`)은 남는다. |
| `run.sh check` | Claude Code의 버전, `claude -p`가 Bedrock으로 답하는지, 인스턴스 메타데이터 서비스에 닿지 않는지, 사용자 `dev`의 권한(`CapEff`)과 경로를 지우지 못하는지, MCP 서버의 도구 목록, 개발팀 역할로 `search`, 셸과 Claude Code의 셸 도구에서 `aws sts get-caller-identity`가 개발팀 역할인지 본다. 찍는 글은 표준 오류까지 계정을 가린다. |
| `run.sh term` | ttyd를 `127.0.0.1:7681`에서만 띄운다(`-i lo`). 페이지를 열 때마다 컨테이너에 새 셸이 뜬다. |
| `run.sh agent <에이전트>` | 리포에서 git이 추적하는 `dev_team/<에이전트>`를 그때 컨테이너 안의 `dev_team/`에 넣는다. 그 자리에 있던 것(Claude Code가 만든 것)은 컨테이너 안에서 `/home/dev/made-by-claude/`로 옮겨 둔다. |
| `run.sh stop` | ttyd와 컨테이너를 멈춘다. 홈은 남는다. |
| `run.sh forget` | 자격 증명 파일 둘을 지운다. |
| `run.sh down` | `stop`과 `forget`. |

### 개발자의 작업 폴더

`/home/dev/work`는 개발자의 checkout이자 Claude Code의 프로젝트 폴더다. 리포에서 git이 추적하는 `dev_team/`, `platform_team/`, `demo_scenes/`, `pyproject.toml`, `uv.lock`(Terraform 상태, `build/`, `.env`는 넣지 않는다)과 이 폴더의 `CLAUDE.md`, `.mcp.json`, `.claude/settings.json`이 들어 있다. `demo_scenes/`가 PATH의 맨 뒤에 있어서 개발자는 `search "…"`, `publish <에이전트>`, `logs <에이전트>`로 친다(작업 폴더의 파일이 `ls`, `cat`, `uv`, `ip`를 가리지 못한다).

영상의 이야기에서 개발자는 Claude Code로 `quality_agent`를 만든다. 그래서 `run.sh up` 뒤의 작업 폴더에는 `dev_team/quality_agent`가 없다. Claude Code가 만든 에이전트는 화면에 보이기만 하고 올리지 않는다. 올리는 것은 리포의 `dev_team/quality_agent`(변형 `v1-vulnerable`, `v2-loop`를 포함한다)다. 뒤의 장면이 그 변형(취약한 라이브러리, 도구를 되풀이해 부르는 판)을 쓰기 때문이다. 만드는 장면과 올리는 장면 사이에 화면 밖에서 `run.sh agent quality_agent`를 돌린다. 작업 폴더를 처음 상태로 되돌리려면 `run.sh up`을 다시 돌린다.

### Claude Code가 묻지 않고 하는 일

`settings.json`의 `permissions.allow`에 있는 것뿐이다.

| 규칙 | 묻지 않고 하는 일 |
|---|---|
| `mcp__hub-catalog__*` | 카탈로그 MCP 서버의 도구(검색과 record 읽기) |
| `Edit(./dev_team/**)` | `dev_team/` 아래의 파일 쓰기와 고치기(에이전트를 만드는 곳) |
| `Bash(search:*)`, `Bash(logs:*)` | 카탈로그 검색, 에이전트의 로그 보기 |
| `Bash(ls:*)`, `Bash(cat:*)` | 작업 폴더의 목록과 파일 보기 |

`permissions.deny`에 있는 것은 묻지 않고 거부한다.

| 규칙 | 까닭 |
|---|---|
| `Read(//run/dev-pc/**)` | 자격 증명 파일 |
| `Edit(./demo_scenes/**)` | 묻지 않고 도는 명령(`search`, `logs`)의 파일 |
| `Edit(./platform_team/**)` | 그 명령이 부르는 허브의 코드 |
| `Edit(./pyproject.toml)`, `Edit(./uv.lock)` | 그 명령이 쓰는 Python 환경 |
| `Edit(./.claude/**)`, `Edit(./.mcp.json)` | Claude Code 자신의 설정과, 묻지 않고 뜨는 MCP 서버 |
| `Edit(./dev_team/**/.claude/**)`, `Edit(./dev_team/**/.mcp.json)`, `Edit(./dev_team/**/CLAUDE.md)` | `dev_team/` 아래는 묻지 않고 쓰는 곳이라서, 그 아래에 다음 세션이 읽을 Claude Code의 폴더(스킬, 훅, 설정), MCP 서버 목록, 지시 파일을 만들지 못하게 한다 |

장면 명령(`search`, `logs`, `ask`, `publish`)은 Python을 `-I`(격리 모드)로 띄우므로, 명령을 부른 폴더(예: Claude Code가 묻지 않고 쓸 수 있는 `dev_team/` 아래)의 파일을 모듈로 불러오지 않고, 부른 쪽의 `PYTHON…` 환경 변수(`PYTHONPATH`, `PYTHONWARNINGS` 등)도 읽지 않는다. 그 밖의 도구는 Claude Code가 화면에서 묻는다. `publish`도 묻는다(이야기에서 올리는 것은 개발자가 직접 친다). 시험(`uv run pytest`)도 묻는다. 권한을 건너뛰는 모드나 플래그는 쓰지 않는다(`run.sh check`만 `claude -p`에 `--allowedTools "Bash(aws sts get-caller-identity --query Arn --output text)"`를 준다. 그 한 명령이 개발팀 역할로 도는지 보는 것이다). Claude Code 2.1.330은 따로 정하지 않으면 auto mode(Claude가 도구 호출의 위험을 스스로 판단해 낮다고 본 것은 묻지 않고 실행한다)로 시작하므로(2026-11-23에 컨테이너에서 처음 띄웠을 때 그렇게 알렸다), 설정이 묻는 모드를 정하고(`"defaultMode": "default"`) auto mode를 끈다(`"disableAutoMode": "disable"`. Claude Code의 settings reference는 이 키가 auto mode를 `Shift+Tab`의 순환에서 빼고, auto mode로 시작했을 세션을 `default`로 시작하게 한다고 적는다. 2026-11-23에 읽었다). `.mcp.json`의 서버는 `enabledMcpjsonServers`로 승인해 둔다.

2026-11-23에 이 설정으로 컨테이너에서 본 것이다(`claude -p`로). MCP 검색 도구는 묻지 않고 돌았다. `demo_scenes/search`를 고쳐 달라는 요청은 Claude Code가 스스로 거절했고, 편집 도구로 한 번 시도해 보라고 하자 그 도구가 `File is in a directory that is denied by your permission settings.`로 거부했다(파일은 바뀌지 않았다). `logs docs_adk 60`은 묻지 않고 돌았다. Claude Code가 `dev_team/x/json.py`(불러오면 표시 파일을 쓰는 두 줄)를 묻지 않고 쓰고 그 폴더에서 `search`를 묻지 않고 돌렸을 때, `search`는 여느 때의 줄을 찍었고 그 파일은 실행되지 않았다. `PYTHONPATH=dev_team/x search …`와 작업 폴더 맨 위에 파일을 쓰는 것(`sitecustomize.py`)은 묻는 일이어서 `claude -p`에서 거절되었다. 장면 명령을 `-I`로 바꾸고 `dev_team/` 아래의 거부 셋을 더한 뒤(11:42 UTC), 컨테이너에서 네 장면 명령은 다른 폴더에서 불러도 잘못된 사용에 종료 값 2로 멈췄고 `search "part specification tool"`은 여느 때의 줄을 찍었다. 부른 쪽의 `PYTHONPATH`와 `PYTHONWARNINGS`가 가리킨 `dev_team/x/planted.py`는 불러오지 않았다. `dev_team/x/.claude/skills/y/SKILL.md`를 쓰라는 요청에는 Claude Code의 쓰기 도구가 `File is in a directory that is denied by your permission settings.`로 거부되었고, 파일은 생기지 않았다(`claude -p`). ttyd의 대화형 세션에서 Claude Code가 물을 때 고를 수 있는 것은 `Yes`, `Yes, and don't ask again for: …`, `No`였고, auto mode로 바꾸는 선택지는 없었다. `Shift+Tab`은 manual, accept edits, plan 사이만 돌았다.

### 2026-11-23에 확인한 것

시각은 UTC다. 허브는 09:58:51에 `make deploy seed preload`를 시작했고, `make preload`는 10:13:50에 끝났다. 그래서 첫 `run.sh up`(10:06)과 첫 `run.sh check`(10:07), Claude Code의 첫 화면들(10:09), 아래 세 가지를 한 Claude Code 세션(10:10~10:13)은 `make deploy`와 `make seed`가 끝나고 `make preload`가 아직 돌 때다. 그때 `spec_assistant`는 승인되어 검색에 나왔고, `docs_adk`는 심사 중이었다. `logs` 명령(10:14)과 두 번째 `run.sh check`(10:16)는 `make preload`가 끝난 뒤다(`parts-tools`, `spec_assistant`, `docs_adk`가 승인되어 있었다).

- 첫 `run.sh check`(20초)는 모두 통과했다. 그때는 아직 이 폴더를 믿는다는 답이 없어서 Claude Code가 "Ignoring 9 permissions.allow entries ... this workspace has not been trusted"를 두 번 찍었다. 두 번째 `run.sh check`(19초)는 그 줄 없이 모두 통과했다. 둘 다 `claude -p`가 4~5초에 답했다. 개발팀 역할에는 Bedrock 권한이 없으므로 그 답은 Bedrock 토큰으로 온 것이다. 인스턴스 메타데이터 서비스는 답하지 않았다. MCP 서버는 개발팀 역할로 도구 넷(`search_discoverable_registry_records`, `search_discoverable_registry_records_paginated`, `list_discoverable_registry_records`, `batch_get_discoverable_registry_record`)을 보였다. `search "part specification tool"`은 `parts-tools`(도구 둘과 그 입력 필드)와 `spec_assistant`를 찍었다. `aws sts get-caller-identity`는 셸에서도, Claude Code의 셸 도구에서도 `assumed-role/hub-dev-role/developer`였다. `awsCredentialExport`의 토큰은 Claude Code의 모델 호출에만 쓰였고 Claude Code가 띄운 도구에는 넘어가지 않았다. 같은 날 지금의 `run.sh`로 돌린 `run.sh check`(19초)도 모두 통과했고, `CapEff:	0000000000000000`과 `RTNETLINK answers: Operation not permitted`를 찍었다.
- `run.sh creds`를 컨테이너가 떠 있는 동안 다시 돌리자, 컨테이너 안에서 본 두 파일의 inode와 수정 시각이 곧바로 이 PC의 새 파일과 같아졌고, 다음 명령(`aws sts get-caller-identity`)이 개발팀 역할로 답했다. `run.sh up`은 3~4초였다(`uv sync` 포함).
- Claude Code를 처음 띄웠을 때 나온 화면은 넷이었다. 글자 모양(theme) 고르기(Dark mode를 골랐다), 보안 안내(Enter), 이 폴더를 믿는지 묻는 창(설정이 미리 허락한 권한을 보이고 기본 선택은 "No, exit"이다. "Yes, I trust this folder"를 골랐다), 그리고 auto mode가 기본 권한 모드가 되었다는 알림이다. 답은 홈의 `~/.claude.json`과 `~/.claude/settings.json`에 남았고, 그 뒤로 `claude`는 2초 남짓에 곧바로 입력 줄로 시작했다. 머리에는 `Claude Code v2.1.330`, `Sonnet 5.5 · Amazon Bedrock`, `~/work`가 나왔고 조직, 이메일, 계정은 나오지 않았다. 처음 띄울 때 Claude Code는 공식 플러그인 마켓플레이스(`anthropics/claude-plugins-official`, GitHub)를 등록해 두었다(`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`인데도. 홈의 `known_marketplaces.json`에 10:09에 받은 것으로 남아 있다). 설치된 플러그인은 없었다.
- 카탈로그 검색: "부품 규격을 읽어 오는 도구가 필요합니다. 허브에 그런 도구가 있나요?"라고 묻자 Claude Code는 셸 명령 `search`를 골랐다. `search "부품 규격"`에는 맞는 record가 없었고, 한 명령으로 돌린 `search "part specification"; search "datasheet"; search "spec"; search "부품"` 가운데 `"part specification"`이 `spec_assistant`와 `parts-tools`를 찾았다(나머지 셋은 맞는 record가 없었다. 13초). "카탈로그 MCP 서버(hub-catalog)로 부품 규격을 읽는 도구를 찾아서, 그 도구의 record를 보여 주세요."라고 하자 MCP 도구 `search_discoverable_registry_records`(검색어 `part specification read tool`)를 불러 `parts-tools`의 record(버전, 설명, Target `Parts`, 도구 둘과 입력 필드)를 보였다(7초). 두 번 다 권한을 묻지 않았다. 이때의 설정은 지금의 것보다 넓었다(작업 폴더 전체의 고치기, `publish`, `uv run pytest`도 묻지 않았다).
- 에이전트 만들기: 같은 세션에서 "템플릿으로 검사 결과와 부품 규격에 답하는 에이전트 quality_agent를 Strands로 만들어 주세요. 도구는 방금 찾은 Parts___get_part_spec을 쓰세요. 파일만 만들고 올리지는 마세요."라고 하자 `dev_team/quality_agent/`에 다섯 파일(템플릿 그대로의 `main.py`와 `hub_tools.py`, `agent.json`, `requirements.txt`, Strands로 쓴 `agent.py`)을 만들었고 올리지 않았다. 그동안 Claude Code는 여섯 번 물었다(화면을 보며 센 것이고, 다섯 번의 화면을 남겼다). `for` 문으로 템플릿과 예시 에이전트의 파일을 읽는 셸 명령 둘, PyPI에서 `strands-agents`의 버전을 찾는 `pip` 명령(거절하고 "패키지 버전은 이 폴더의 uv.lock에 있는 것을 쓰고, 계속 만들어 주세요."라고 답했다), `cd`와 상대 경로의 `find`(Read의 `deny`가 있으면 묻는다), 폴더를 만들고 템플릿을 복사하는 `mkdir`와 `cp`, `requirements.txt`에 줄을 더하는 `echo >>`다. 파일 쓰기와 `grep`은 묻지 않았다. 컨테이너에 `python3` 명령이 없어서, Claude Code는 만든 코드의 문법을 확인하지 못했다고 말했다. 이것도 지금보다 넓은 설정에서였다. 지금의 설정에서는 `dev_team/` 밖의 파일 쓰기도 묻는다.
