# 에이전트 템플릿

허브에 에이전트를 올리려는 개발 팀이 복사해서 시작하는 폴더다. 허브를 처음 보는 사람도 이 문서만 읽으면 올릴 수 있다.

## 파일

| 파일 | 설명 |
|---|---|
| `agent.py` | 팀이 쓴다(이 폴더에는 없다). `run(prompt) -> (answer, tools_used)` 함수 하나를 만든다. |
| `main.py` | Runtime의 진입점이다. 요청을 받아 `agent.run`을 부르고 답을 돌려준다. 고치지 않는다. |
| `hub_tools.py` | 허브의 공유 도구를 부르는 `call_tool(tool_id, arguments)`다. 도구 게이트웨이에 서명한 요청을 보내고, 도구가 답한 text를 돌려준다. 게이트웨이가 거부하면 `ERROR: ...`로 돌려준다. |
| `agent.json` | 신청서다. 이름, 팀, 프레임워크, 쓸 도구의 목록이 들어 있다. |
| `requirements.txt` | 에이전트가 쓰는 패키지다. 아래 규칙을 지켜야 한다. |
| `publish.sh` | 코드를 올리고 승인을 요청하는 명령이다. |

## 팀이 하는 일

1. 이 폴더를 복사한다.
2. `agent.py`에 `run(prompt) -> (answer, tools_used)`를 쓴다. 도구는 `hub_tools.call_tool("Parts___get_part_spec", {"part_id": "P-100"})`처럼 부른다. `agent.py`가 `import`하는 패키지 중 표준 라이브러리가 아닌 것은 `requirements.txt`에 모두 적는다. 코드는 폴더 맨 위의 `.py` 파일로 둔다. 하위 폴더의 파일은 올라가지 않는다.
3. `agent.json`을 채운다. 이름은 소문자로 시작하는 소문자, 숫자, 밑줄 3~31자이고, 도구는 카탈로그에 있는 `<Target>___<tool>` 이름이다.
4. `publish.sh <복사한 폴더>`를 실행한다. 어느 폴더에서 실행해도 된다.

`publish.sh`는 코드를 제출함에 올리고, 신청서를 카탈로그에 쓰고, 승인을 요청한다. 승인을 요청하면 호스팅 심사가 시작된다(읽기, 검사, 권한, 배포, 등록, 시험 호출, 승인).

## 심사가 확인하고 거부하는 것

코드 묶음 맨 위에 `main.py`와 `requirements.txt`가 있어야 한다. `requirements.txt`에는 패키지 색인에 있는 패키지를 이름으로 적고 버전은 `==`로 고정한다. 아래는 거부한다.

- pip 옵션(`-r`, `-e`, `--index-url`, `--hash`): 설치 위치를 바꾸거나 다른 파일을 끌어올 수 있다.
- 직접 참조(`pkg @ URL`, URL, `file:`, 경로): 검사가 내용을 볼 수 없는 코드가 설치된다.
- 환경 표시(`; python_version >= "3.10"`): 검사와 배포가 서로 다른 기계를 기준으로 판단해 검사에서 빠진 줄이 배포에서 설치될 수 있다. Runtime은 Linux aarch64, CPython 3.13 하나다.

설치는 그 환경의 wheel만 받는다. 템플릿의 `bedrock-agentcore`, `boto3`, `botocore`는 `main.py`와 `hub_tools.py`가 쓰므로 지우지 않는다. Runtime에는 `requirements.txt`에 적은 패키지만 있다.

## 팀이 쓰지 않는 것

배포 설정과 실행 역할은 쓰지 않는다. 플랫폼이 만든다. 제출물에 배포 설정이 들어 있어도 쓰지 않는다. Runtime에는 환경 변수 `HUB_REGION`, `TOOL_GATEWAY_URL`, `MODEL_ID`, `AGENT_NAME`이 들어 있다.
