# 에이전트 템플릿

허브에 에이전트를 올리려는 개발 팀이 복사해서 시작하는 폴더입니다. 허브를 처음 보는 사람도 이 문서만 읽으면 올릴 수 있습니다.

## 파일

| 파일 | 설명 |
|---|---|
| `agent.py` | 팀이 씁니다(이 폴더에는 없습니다). `run(prompt) -> (answer, tools_used)` 함수 하나를 만듭니다. |
| `main.py` | Runtime의 진입점입니다. 요청을 받아 `agent.run`을 부르고 답을 돌려줍니다. 고치지 않습니다. |
| `hub_tools.py` | 허브의 공유 도구를 부르는 `call_tool(tool_id, arguments)`입니다. 도구 게이트웨이에 서명한 요청을 보내고, 도구가 답한 text를 돌려줍니다. 게이트웨이가 거부하거나 호출이 실패하면 예외를 내지 않고 `ERROR: ...`로 돌려줍니다. 예외는 종류와 짧은 메시지(300자까지)로만 알리고, 그 안의 12자리 숫자(역할 ARN의 계정 ID 같은 것)는 `<ACCOUNT>`로 가립니다(`error_text`). 에이전트의 답에 실려 화면에 나갈 수 있기 때문입니다. |
| `agent.json` | 신청서입니다. 이름, 팀, 프레임워크, 쓸 도구의 목록이 들어 있습니다. |
| `requirements.txt` | 에이전트가 쓰는 패키지입니다. 아래 규칙을 지켜야 합니다. |
| `publish.sh` | 코드를 올리고 승인을 요청하는 명령입니다. |

## 팀이 하는 일

1. 이 폴더를 복사합니다.
2. `agent.py`에 `run(prompt) -> (answer, tools_used)`를 씁니다. 도구는 `hub_tools.call_tool("Parts___get_part_spec", {"part_id": "P-100"})`처럼 부릅니다. `agent.py`가 `import`하는 패키지 중 표준 라이브러리가 아닌 것은 `requirements.txt`에 모두 적습니다. 코드는 폴더 맨 위의 `.py` 파일로 둡니다. 하위 폴더의 파일은 올라가지 않습니다. 폴더 맨 위의 `.py` 파일은 이름만 맞으면 모두 올라가므로, 비밀 값을 코드에 적지 않습니다.
3. `agent.json`을 채웁니다. 이름은 소문자로 시작하는 소문자와 숫자의 마디를 밑줄 하나로 이은 것이고 3~31자입니다(`quality_agent`는 되고 `agent_1`, `Quality`, `quality__agent`는 안 됩니다). 도구는 카탈로그에 있는 `<Target>___<tool>` 이름입니다. 허브의 도구를 하나도 부르지 않는 에이전트(도구가 있어도 에이전트 안에서 도는 것뿐인 에이전트)는 빈 목록 `[]`을 적습니다(예: `dev_team/preloaded_agents/docs_adk`). 허브는 이름으로 정책 이름(48자까지)과 Runtime 이름(`<prefix>_<에이전트>`)을 만듭니다. 이름이 길어 정책 이름이 넘치면 `publish.sh`가 거부하고, 에이전트 이름이 몇 자까지 될 수 있는지 알려 줍니다. Runtime 이름은 31자까지의 에이전트 이름이면 언제나 맞습니다.
4. `publish.sh <복사한 폴더>`를 실행합니다. 어느 폴더에서 실행해도 됩니다. 허브의 접두어와 리전은 `make`와 같은 규칙으로 리포의 `.env`에서 읽고([시작하기의 `.env`](../../docs/getting-started.md#env)), 결과 줄에 어느 허브(접두어, 리전)에 올렸는지 출력합니다.

`publish.sh`는 코드를 제출 버킷에 올리고, 신청서를 카탈로그에 쓰고, 승인을 요청합니다. 승인을 요청하면 호스팅 심사가 시작됩니다(읽기, 검사, 권한, 배포, 등록, 시험 호출, 승인).

## 심사가 확인하고 거부하는 것

코드 패키지 맨 위에 `main.py`와 `requirements.txt`가 있어야 합니다. `requirements.txt`에는 패키지 색인에 있는 패키지를 이름으로 적고 버전은 `==`로 고정합니다. 아래는 거부합니다.

- pip 옵션(`-r`, `-e`, `--index-url`, `--hash`): 설치 위치를 바꾸거나 다른 파일을 끌어올 수 있습니다.
- 직접 참조(`pkg @ URL`, URL, `file:`, 경로): 검사가 내용을 볼 수 없는 코드가 설치됩니다.
- 환경 표시(`; python_version >= "3.10"`): 검사와 배포가 서로 다른 기계를 기준으로 판단해 검사에서 빠진 줄이 배포에서 설치될 수 있습니다. Runtime은 Linux aarch64, CPython 3.13 하나입니다.

설치는 그 환경의 wheel만 받습니다. 템플릿의 `bedrock-agentcore`, `boto3`, `botocore`는 `main.py`와 `hub_tools.py`가 쓰므로 지우지 않습니다. `aws-opentelemetry-distro`도 지우지 않습니다. 허브는 Runtime을 `opentelemetry-instrument main.py`로 실행해 에이전트가 trace를 내게 하는데, 그 명령이 이 패키지에 들어 있습니다. AgentCore 개발자 안내서의 코드 배포 문제 해결("Troubleshooting direct code deployment", 2026-11-22에 읽었습니다)은 Node.js에서 이 명령에 필요한 패키지가 코드 패키지에 없으면 Runtime을 만들 때 실패한다고 적고, Python의 경우는 적지 않습니다. 이 패키지 없이 실행하는 것은 여기서 해 보지 않았습니다. Runtime에는 `requirements.txt`에 적은 패키지만 있습니다.

## 팀이 쓰지 않는 것

배포 설정과 실행 역할은 쓰지 않습니다. 플랫폼이 만듭니다. 제출물에 배포 설정이 들어 있어도 쓰지 않습니다. Runtime에는 환경 변수 `HUB_REGION`, `TOOL_GATEWAY_URL`, `MODEL_ID`, `AGENT_NAME`이 들어 있습니다.
