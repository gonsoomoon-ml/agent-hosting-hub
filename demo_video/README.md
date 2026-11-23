# 시연 영상

허브의 시연 영상을 만드는 데 쓰는 것을 모은 폴더다. 영상의 결과물과 녹화의 원본, 개발자 PC의 홈과 자격 증명 파일은 `out/` 아래에 생기고 git에 올라가지 않는다(`.gitignore`).

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

장면 명령(`search`, `logs`, `ask`, `publish`)은 Python을 `-P`로 띄우므로, 명령을 부른 폴더(예: Claude Code가 묻지 않고 쓸 수 있는 `dev_team/` 아래)의 파일을 모듈로 불러오지 않는다. 그 밖의 도구는 Claude Code가 화면에서 묻는다. `publish`도 묻는다(이야기에서 올리는 것은 개발자가 직접 친다). 시험(`uv run pytest`)도 묻는다. 권한을 건너뛰는 모드나 플래그는 쓰지 않는다(`run.sh check`만 `claude -p`에 `--allowedTools "Bash(aws sts get-caller-identity --query Arn --output text)"`를 준다. 그 한 명령이 개발팀 역할로 도는지 보는 것이다). Claude Code 2.1.330은 따로 정하지 않으면 auto mode(Claude가 도구 호출의 위험을 스스로 판단해 낮다고 본 것은 묻지 않고 실행한다)로 시작하므로(2026-11-23에 컨테이너에서 처음 띄웠을 때 그렇게 알렸다), 설정이 묻는 모드를 정하고(`"defaultMode": "default"`) auto mode를 끈다(`"disableAutoMode": "disable"`. Claude Code의 settings reference는 이 키가 auto mode를 `Shift+Tab`의 순환에서 빼고, auto mode로 시작했을 세션을 `default`로 시작하게 한다고 적는다. 2026-11-23에 읽었다). `.mcp.json`의 서버는 `enabledMcpjsonServers`로 승인해 둔다.

2026-11-23에 이 설정으로 컨테이너에서 본 것이다(`claude -p`로). MCP 검색 도구는 묻지 않고 돌았다. `demo_scenes/search`를 고쳐 달라는 요청은 Claude Code가 스스로 거절했고, 편집 도구로 한 번 시도해 보라고 하자 그 도구가 `File is in a directory that is denied by your permission settings.`로 거부했다(파일은 바뀌지 않았다). `logs docs_adk 60`은 묻지 않고 돌았다. Claude Code가 `dev_team/x/json.py`(불러오면 표시 파일을 쓰는 두 줄)를 묻지 않고 쓰고 그 폴더에서 `search`를 묻지 않고 돌렸을 때, `search`는 여느 때의 줄을 찍었고 그 파일은 실행되지 않았다. `PYTHONPATH=dev_team/x search …`와 작업 폴더 맨 위에 파일을 쓰는 것(`sitecustomize.py`)은 묻는 일이어서 `claude -p`에서 거절되었다. ttyd의 대화형 세션에서 Claude Code가 물을 때 고를 수 있는 것은 `Yes`, `Yes, and don't ask again for: …`, `No`였고, auto mode로 바꾸는 선택지는 없었다. `Shift+Tab`은 manual, accept edits, plan 사이만 돌았다.

### 2026-11-23에 확인한 것

시각은 UTC다. 허브는 09:58:51에 `make deploy seed preload`를 시작했고, `make preload`는 10:13:50에 끝났다. 그래서 첫 `run.sh up`(10:06)과 첫 `run.sh check`(10:07), Claude Code의 첫 화면들(10:09), 아래 세 가지를 한 Claude Code 세션(10:10~10:13)은 `make deploy`와 `make seed`가 끝나고 `make preload`가 아직 돌 때다. 그때 `spec_assistant`는 승인되어 검색에 나왔고, `docs_adk`는 심사 중이었다. `logs` 명령(10:14)과 두 번째 `run.sh check`(10:16)는 `make preload`가 끝난 뒤다(`parts-tools`, `spec_assistant`, `docs_adk`가 승인되어 있었다).

- 첫 `run.sh check`(20초)는 모두 통과했다. 그때는 아직 이 폴더를 믿는다는 답이 없어서 Claude Code가 "Ignoring 9 permissions.allow entries ... this workspace has not been trusted"를 두 번 찍었다. 두 번째 `run.sh check`(19초)는 그 줄 없이 모두 통과했다. 둘 다 `claude -p`가 4~5초에 답했다. 개발팀 역할에는 Bedrock 권한이 없으므로 그 답은 Bedrock 토큰으로 온 것이다. 인스턴스 메타데이터 서비스는 답하지 않았다. MCP 서버는 개발팀 역할로 도구 넷(`search_discoverable_registry_records`, `search_discoverable_registry_records_paginated`, `list_discoverable_registry_records`, `batch_get_discoverable_registry_record`)을 보였다. `search "part specification tool"`은 `parts-tools`(도구 둘과 그 입력 필드)와 `spec_assistant`를 찍었다. `aws sts get-caller-identity`는 셸에서도, Claude Code의 셸 도구에서도 `assumed-role/hub-dev-role/developer`였다. `awsCredentialExport`의 토큰은 Claude Code의 모델 호출에만 쓰였고 Claude Code가 띄운 도구에는 넘어가지 않았다. 같은 날 지금의 `run.sh`로 돌린 `run.sh check`(19초)도 모두 통과했고, `CapEff:	0000000000000000`과 `RTNETLINK answers: Operation not permitted`를 찍었다.
- `run.sh creds`를 컨테이너가 떠 있는 동안 다시 돌리자, 컨테이너 안에서 본 두 파일의 inode와 수정 시각이 곧바로 이 PC의 새 파일과 같아졌고, 다음 명령(`aws sts get-caller-identity`)이 개발팀 역할로 답했다. `run.sh up`은 3~4초였다(`uv sync` 포함).
- Claude Code를 처음 띄웠을 때 나온 화면은 넷이었다. 글자 모양(theme) 고르기(Dark mode를 골랐다), 보안 안내(Enter), 이 폴더를 믿는지 묻는 창(설정이 미리 허락한 권한을 보이고 기본 선택은 "No, exit"이다. "Yes, I trust this folder"를 골랐다), 그리고 auto mode가 기본 권한 모드가 되었다는 알림이다. 답은 홈의 `~/.claude.json`과 `~/.claude/settings.json`에 남았고, 그 뒤로 `claude`는 2초 남짓에 곧바로 입력 줄로 시작했다. 머리에는 `Claude Code v2.1.330`, `Sonnet 5.5 · Amazon Bedrock`, `~/work`가 나왔고 조직, 이메일, 계정은 나오지 않았다. 처음 띄울 때 Claude Code는 공식 플러그인 마켓플레이스(`anthropics/claude-plugins-official`, GitHub)를 등록해 두었다(`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`인데도. 홈의 `known_marketplaces.json`에 10:09에 받은 것으로 남아 있다). 설치된 플러그인은 없었다.
- 카탈로그 검색: "부품 규격을 읽어 오는 도구가 필요합니다. 허브에 그런 도구가 있나요?"라고 묻자 Claude Code는 셸 명령 `search`를 골랐다. `search "부품 규격"`에는 맞는 record가 없었고, 한 명령으로 돌린 `search "part specification"; search "datasheet"; search "spec"; search "부품"` 가운데 `"part specification"`이 `spec_assistant`와 `parts-tools`를 찾았다(나머지 셋은 맞는 record가 없었다. 13초). "카탈로그 MCP 서버(hub-catalog)로 부품 규격을 읽는 도구를 찾아서, 그 도구의 record를 보여 주세요."라고 하자 MCP 도구 `search_discoverable_registry_records`(검색어 `part specification read tool`)를 불러 `parts-tools`의 record(버전, 설명, Target `Parts`, 도구 둘과 입력 필드)를 보였다(7초). 두 번 다 권한을 묻지 않았다. 이때의 설정은 지금의 것보다 넓었다(작업 폴더 전체의 고치기, `publish`, `uv run pytest`도 묻지 않았다).
- 에이전트 만들기: 같은 세션에서 "템플릿으로 검사 결과와 부품 규격에 답하는 에이전트 quality_agent를 Strands로 만들어 주세요. 도구는 방금 찾은 Parts___get_part_spec을 쓰세요. 파일만 만들고 올리지는 마세요."라고 하자 `dev_team/quality_agent/`에 다섯 파일(템플릿 그대로의 `main.py`와 `hub_tools.py`, `agent.json`, `requirements.txt`, Strands로 쓴 `agent.py`)을 만들었고 올리지 않았다. 그동안 Claude Code는 여섯 번 물었다(화면을 보며 센 것이고, 다섯 번의 화면을 남겼다). `for` 문으로 템플릿과 예시 에이전트의 파일을 읽는 셸 명령 둘, PyPI에서 `strands-agents`의 버전을 찾는 `pip` 명령(거절하고 "패키지 버전은 이 폴더의 uv.lock에 있는 것을 쓰고, 계속 만들어 주세요."라고 답했다), `cd`와 상대 경로의 `find`(Read의 `deny`가 있으면 묻는다), 폴더를 만들고 템플릿을 복사하는 `mkdir`와 `cp`, `requirements.txt`에 줄을 더하는 `echo >>`다. 파일 쓰기와 `grep`은 묻지 않았다. 컨테이너에 `python3` 명령이 없어서, Claude Code는 만든 코드의 문법을 확인하지 못했다고 말했다. 이것도 지금보다 넓은 설정에서였다. 지금의 설정에서는 `dev_team/` 밖의 파일 쓰기도 묻는다.
