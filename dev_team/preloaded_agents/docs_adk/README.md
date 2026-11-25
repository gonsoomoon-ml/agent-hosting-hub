# docs_adk

사내 설계 표준을 묻는 질문에 답하는 에이전트입니다. Google ADK(Agent Development Kit)로 만들었습니다. 허브에 미리 올려 둔 에이전트 둘 가운데 하나로, `make preload`가 다른 팀의 에이전트와 같은 길로 제출하고 같은 호스팅 심사를 거칩니다. 다른 하나는 코드가 없는 [spec_assistant](../spec_assistant/README.md)입니다.

## 파일

| 파일 | 내용 |
|---|---|
| `agent.py` | ADK의 `LlmAgent` 하나와 도구 `find_standard(topic)` 하나. 질문마다 새 세션을 만들고, 실패하면 `ERROR: ...`를 답합니다. |
| `main.py`, `hub_tools.py` | 템플릿의 것 그대로입니다. |
| `agent.json` | 신청서. 허브의 도구를 하나도 적지 않습니다(`"tools": []`). |
| `requirements.txt` | 템플릿의 네 줄에 `google-adk==2.14.1`을 더했습니다. |

`find_standard`는 `agent.py`의 `STANDARDS`에 적은 예시 표준 셋(`STD-01` API 버전, `STD-02` 로그, `STD-03` 시간 제한과 재시도)에서 맞는 것을 돌려줍니다. 에이전트 안에서 도는 함수라 도구 게이트웨이를 지나지 않습니다. 그래서 도구 정책이 없고, 도구 호출 수의 메트릭에도 나오지 않습니다.

## 모델

ADK의 모델 자리(`BaseLlm`)에 작은 클래스 `BedrockConverse`를 두고, boto3로 Amazon Bedrock의 Converse API를 부릅니다. 모델은 허브의 `MODEL_ID`이고, 스트리밍은 하지 않습니다.

ADK가 Gemini 밖의 모델에 쓰는 LiteLLM은 쓰지 않습니다. 2026-11-22에 `litellm==1.106.2`는 Linux wheel이 `manylinux_2_28`뿐이라 배포 build와 같은 설치 명령이 멈췄고, 검사가 그 묶음에서 알려진 취약점 13개를 찾았습니다.

## 버전과 크기

- `google-adk`는 2.14.1로 고정했습니다. 2026-11-22의 최신인 2.15.0은 `watchdog>=7`을 요구해서, `quality_agent`의 테스트가 쓰는 `strands-agents==1.65.0`과 한 테스트 환경에 둘 수 없습니다.
- 코드 패키지는 압축 약 46 MB(46,291,484바이트)입니다. AgentCore 개발자 안내서가 적는 직접 코드 배포의 한도는 압축 250 MB, 풀어서 750 MB이고, 이 한도는 확인하지 않았습니다.

## 허브에서 받는 통제

에이전트 게이트웨이의 target(`DocsAdk`)으로 다른 에이전트와 같은 진입의 통제를 받습니다. 진입 정책, 비밀값 검사, 전사 정책, 커스텀 가드레일, 멈춤 명령(`stop.sh`)이 닿습니다. 커스텀 가드레일과 멈춤 명령은 이 에이전트로 확인하지 않았습니다.

## AWS에서 본 것

2026-11-22에 `us-west-2`, 접두어 `hub`, 기본 모델로 돌렸습니다.

- 심사는 약 6분(364초)에 `SUCCEEDED`였습니다. 대부분은 Deploy(258초)입니다.
- `What is our standard for versioning an API?`에 200과 함께 API 버전 표준의 세 규칙이 왔고, `tools_used`는 `["find_standard"]`였습니다.
- 전사 정책 `guard_prompt`를 적용 모드로 켠 허브에서는 숨은 지시가 든 요청이 첫 호출부터 403이었습니다.
- Runtime의 로그 그룹에 오류 줄은 없었습니다. 경고 줄 넷은 무엇 때문인지 알아보지 않았습니다.

## 로컬에서 테스트하기

```bash
uv run pytest tests/test_docs_adk.py -q
```

가짜 Bedrock 클라이언트로 ADK의 runner, 도구, 모델 클래스를 실제로 돌립니다. AWS를 부르지 않습니다.
