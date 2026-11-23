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
- 한계: Bedrock 토큰 파일은 컨테이너의 사용자(Claude Code의 도구와 같은 사용자)가 읽을 수 있는 파일이다. Claude Code의 파일 읽기 도구는 그 폴더를 읽지 못하게 막았지만(`settings.json`의 `deny`), 셸 명령으로 읽는 것까지 막지는 못한다. 그 토큰으로 할 수 있는 것은 두 모델의 호출뿐이다.
- 이 PC가 EC2 인스턴스라면 컨테이너에서 인스턴스 메타데이터 서비스에 닿을 수 있다. `run.sh up`은 SDK가 그곳을 묻지 않게 하고(`AWS_EC2_METADATA_DISABLED=true`), 그 주소를 컨테이너의 네트워크에서 막는다(root가 한 번 넣는 blackhole 경로. 사용자 `dev`에게는 지울 권한이 없다).

### `run.sh`

| 명령 | 하는 일 |
|---|---|
| `run.sh build` | 이미지 `hub-dev-pc`를 만든다. build context 없이 만들므로 이 PC의 파일은 이미지에 들어가지 않는다. |
| `run.sh creds` | 자격 증명 둘을 만들어 파일로 둔다. 컨테이너가 떠 있는 동안 다시 돌려도 된다(파일을 바꿔 두면 컨테이너는 다음 명령부터 새 것을 읽는다). |
| `run.sh up` | 컨테이너를 새로 띄운다. 작업 폴더를 새로 만들고(아래), `.mcp.json`을 허브의 카탈로그 ID로 채우고, `uv sync`를 한 번 돌린다. 홈(`demo_video/out/dev-pc/home`)은 남는다. |
| `run.sh check` | Claude Code의 버전, `claude -p`가 Bedrock으로 답하는지, 인스턴스 메타데이터 서비스에 닿지 않는지, MCP 서버의 도구 목록, 개발팀 역할로 `search`, 셸과 Claude Code의 셸 도구에서 `aws sts get-caller-identity`가 개발팀 역할인지 본다. |
| `run.sh term` | ttyd를 `127.0.0.1:7681`에서만 띄운다(`-i lo`). 페이지를 열 때마다 컨테이너에 새 셸이 뜬다. |
| `run.sh agent <에이전트>` | 리포의 에이전트를 작업 폴더의 `dev_team/`에 넣는다. 그 자리에 있던 것(Claude Code가 만든 것)은 `/home/dev/made-by-claude/`로 옮겨 둔다. |
| `run.sh stop` | ttyd와 컨테이너를 멈춘다. 홈은 남는다. |
| `run.sh forget` | 자격 증명 파일 둘을 지운다. |
| `run.sh down` | `stop`과 `forget`. |

### 개발자의 작업 폴더

`/home/dev/work`는 개발자의 checkout이자 Claude Code의 프로젝트 폴더다. 리포에서 git이 추적하는 `dev_team/`, `platform_team/`, `demo_scenes/`, `pyproject.toml`, `uv.lock`(Terraform 상태, `build/`, `.env`는 넣지 않는다)과 이 폴더의 `CLAUDE.md`, `.mcp.json`, `.claude/settings.json`이 들어 있다. `demo_scenes/`가 PATH에 있어서 개발자는 `search "…"`, `publish <에이전트>`, `logs <에이전트>`로 친다.

영상의 이야기에서 개발자는 Claude Code로 `quality_agent`를 만든다. 그래서 `run.sh up` 뒤의 작업 폴더에는 `dev_team/quality_agent`가 없고, 리포의 `quality_agent`(변형 `v1-vulnerable`, `v2-loop`를 포함한다)는 `/home/dev/prepared/`에 따로 있다. Claude Code가 만든 에이전트는 화면에 보이기만 하고 올리지 않는다. 올리는 것은 리포의 `dev_team/quality_agent`다. 뒤의 장면이 그 변형(취약한 라이브러리, 도구를 되풀이해 부르는 판)을 쓰기 때문이다. 만드는 장면과 올리는 장면 사이에 화면 밖에서 `run.sh agent quality_agent`를 돌린다. 작업 폴더를 처음 상태로 되돌리려면 `run.sh up`을 다시 돌린다.

### Claude Code가 묻지 않고 하는 일

`settings.json`의 `permissions.allow`에 있는 것뿐이다. 카탈로그 MCP 서버(`hub-catalog`)의 도구, 작업 폴더의 파일 읽기와 고치기, 셸 명령 `search`, `logs`, `publish`, `ls`, `cat`, `uv run pytest`. 그 밖의 도구는 Claude Code가 화면에서 묻는다. 권한을 건너뛰는 모드나 플래그는 쓰지 않는다. `.mcp.json`의 서버는 `enabledMcpjsonServers`로 승인해 둔다.
