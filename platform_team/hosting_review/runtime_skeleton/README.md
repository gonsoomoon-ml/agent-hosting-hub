# 런타임 뼈대

심사의 배포 단계(CodeBuild, `buildspec_deploy.yml`)가 팀의 코드를 AgentCore Runtime에 올릴 때 쓰는 배포 설정의 틀이다. 이 폴더의 파일은 플랫폼 팀이 관리한다. 개발 팀이 내는 것은 코드(`main.py`와 그 밖의 파일)와 `requirements.txt`뿐이다. 제출물에 배포 설정이 들어 있어도 배포 build는 그것을 쓰지 않는다.

| 파일 | 역할 |
|---|---|
| `agentcore.json.tmpl` | AgentCore CLI 프로젝트의 `agentcore/agentcore.json` 틀. Runtime 하나(이름 `agent`, 빌드 `CodeZip`, 진입점 `main.py`, 코드 위치 `app/agent`, `PYTHON_3_13`), 실행 역할, 환경 변수 네 개가 들어 있고 메모리는 없다. `${이름}` 자리에 값이 들어간다. |

## 배포 build가 하는 일

`deploy_build.py`가 아래 순서로 한다.

1. 제출물을 카탈로그 기록에 적힌 object version으로 S3에서 받아 푼다. 위험한 경로가 있거나, `main.py`나 `requirements.txt`가 없거나, `requirements.txt`가 아래 규칙에 맞지 않으면 멈춘다.
2. 고정한 CLI(`@aws/agentcore` 1.0.3)로 프로젝트를 만든다: `agentcore create --name <프로젝트> --template agent-python-minimal --skip-install --skip-git`. 프로젝트 이름은 접두어와 에이전트 이름을 이은 것이다(예: `hubQualityAgent`). 이 프로젝트에서 쓰는 것은 CDK 앱(`agentcore/cdk/`)이다.
3. 프로젝트의 `app/agent/`를 비우고 제출물로 채운다. 제출물에 있던 `pyproject.toml`, `uv.lock`, `uv.toml`, `.python-version`은 거부하지 않고 지운다. 무엇을 어디서 설치할지는 플랫폼이 정한다. buildspec도 `UV_NO_CONFIG=1`을 두어 uv가 설정 파일을 하나도 읽지 않게 한다.
4. `requirements.txt`로 `app/agent/pyproject.toml`을 쓴다. CLI의 CodeZip 패키징은 코드 위치에 있는 `pyproject.toml`의 의존성을 설치하기 때문이다.
5. `agentcore.json.tmpl`을 채워 `agentcore/agentcore.json`을 쓴다. 들어가는 값은 프로젝트 이름, 허가 단계가 만든 실행 역할(`ROLE_ARN`), 환경 변수 `HUB_REGION`, `TOOL_GATEWAY_URL`, `MODEL_ID`, `AGENT_NAME`이다.
6. `agentcore/cdk/`에서 `npm install`을 하고 `agentcore deploy --json --skip-bootstrap`을 돌린다. 스택 `AgentCore-<프로젝트>-default`가 없으면 만들고, 있으면 갱신한다. 갱신하면 Runtime에 새 버전이 생긴다.
7. 출력에서 Runtime ARN(키에 `RuntimeArnOutput`이 들어 있는 값)을 읽어 SSM `/<접두어>/agents/<에이전트>/runtime_arn`에 쓴다. 다음 단계(Entry)가 이 값을 읽는다.

## `requirements.txt` 규칙

`requirements.txt`에는 패키지 색인에 있는 패키지를 이름으로 적는다. 쓸 수 있는 것은 이름, extras, 버전뿐이다. 검사 단계는 다음을 거부한다.

- pip 옵션(`-r`, `-e`, `--index-url`, `--hash`)
- 직접 참조(`pkg @ URL`, URL, `file:`, 로컬 경로)
- 환경 표시(`; python_version >= "3.10"`, `; platform_release == ""` 같은 것). 검사 단계의 pip는 환경 표시를 검사하는 기계에 대어 보고, 배포의 uv는 Runtime 대상(Linux aarch64, CPython 3.13)에 대어 본다. 그래서 검사에서는 빠지고 배포에서는 설치되는 줄이 생길 수 있다. 대상이 하나로 정해져 있으니 환경 표시는 쓸 일이 없다.

배포 build는 같은 규칙(`submission_check.parse_requirements`)으로 한 번 더 확인한다.

그래서 `requirements.txt`에 적힌 패키지는 검사 단계가 모두 검사하고, 배포가 모두 설치한다. 두 단계 모두 기본 색인(PyPI)에서 wheel만 받고, sdist의 `setup.py`는 실행하지 않는다. 다만 버전을 범위로 적으면 두 단계가 따로 고르므로, `==`로 고정해야 검사한 버전과 같아진다.

간접 의존성은 이렇게 보장되지 않는다. 두 단계가 따로 고르므로, 그 사이에 새 버전이 나오거나 어떤 패키지의 의존성에 환경 표시가 있으면 배포가 설치하는 것이 검사한 것과 다를 수 있다. 운영 환경이라면 검사 단계가 배포 대상에 맞춰 `uv pip compile`로 간접 의존성까지 고정한 목록을 만들어 검사하고, 배포는 그 목록을 그대로 설치하게 한다.

## OTel

`instrumentation.enableOtel`은 `false`다. 켜 두면 CLI가 진입점을 `opentelemetry-instrument main.py`로 감싸는데, 이 명령은 `aws-opentelemetry-distro` 패키지가 있어야 돈다. 팀의 `requirements.txt`에는 보통 이 패키지가 없다.
