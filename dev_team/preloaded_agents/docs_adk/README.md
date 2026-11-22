# docs_adk

사내 설계 표준을 묻는 질문에 답하는 에이전트다. Google ADK(Agent Development Kit)로 만들었다. 허브에 처음부터 올라와 있는 두 에이전트 가운데 하나로, 플랫폼팀의 `make preload`가 다른 팀의 에이전트와 같은 길로 제출하고(`publish_agent.publish`) 같은 호스팅 심사(읽기, 검사, 권한, 배포, 등록, 시험 호출, 승인)를 거친다. 다른 하나인 [spec_assistant](../spec_assistant/README.md)는 코드가 없는 harness라 심사를 거치지 않는다.

## 파일

| 파일 | 내용 |
|---|---|
| `agent.py` | ADK의 `LlmAgent` 하나와 도구 `find_standard(topic)` 하나. 질문마다 새 runner와 세션을 만들므로 한 사람의 대화가 다른 사람에게 가지 않는다. 모델 호출이나 설정이 실패하면 예외를 내지 않고 `ERROR: ...`를 답한다. |
| `main.py`, `hub_tools.py` | 템플릿의 것 그대로다(`tests/test_template_copies.py`가 확인한다). Runtime은 다른 에이전트와 같이 `opentelemetry-instrument main.py`로 뜬다. 이 에이전트는 `hub_tools.py`에서 예외를 짧게 적는 `error_text`만 쓰고, 도구 게이트웨이는 부르지 않는다. |
| `agent.json` | 신청서. 허브의 도구를 하나도 적지 않는다(`"tools": []`). |
| `requirements.txt` | 템플릿의 네 줄에 `google-adk==2.14.1`을 더했다. |

## 도구는 에이전트 안에서 돈다

`find_standard`는 예시 표준 셋(`STD-01` API 버전, `STD-02` 로그, `STD-03` 시간 제한과 재시도) 가운데 질문의 주제에 맞는 것을 돌려준다. 맞는 것이 없으면 어떤 주제의 표준이 있는지 알려 준다. 표준은 `agent.py`의 `STANDARDS`에 적혀 있다. 에이전트의 프로세스 안에서 도는 함수이므로 도구 게이트웨이를 지나지 않는다. 그래서 신청서의 도구 목록이 비어 있고, 심사의 Grant는 이 에이전트에 도구 정책을 만들지 않는다(다른 에이전트의 것도 지우지 않는다). 도구 게이트웨이의 정책은 이 도구에 닿지 않는다.

## 모델

ADK는 Gemini 밖의 모델을 LiteLLM으로 부른다(ADK 2.14.1의 `google.adk.models.lite_llm`. Amazon Bedrock은 `bedrock/<모델 ID>`). 이 에이전트는 그 길을 쓰지 않는다. 2026-11-22에 심사의 규칙 그대로 확인했을 때 `litellm==1.106.2`(ADK가 받는 범위 `<1.106.3`의 마지막 판)는 두 가지에 걸렸다. 그 판의 Linux wheel은 `manylinux_2_28`뿐이어서, 배포 build의 설치(`uv pip install --only-binary :all: --python-platform aarch64-manylinux2014 --python-version 3.13`)가 `litellm==1.106.2 has no usable wheels`로 멈췄다. 또 검사(`pip-audit` 2.10.1, `PIP_ONLY_BINARY=:all:`)는 그 묶음이 끌어온 `filelock 3.32.7`에서 알려진 취약점 13개를 찾았다(고친 판 4.2.1).

그래서 ADK의 모델 자리(`BaseLlm`)에 작은 클래스 `BedrockConverse`를 두고, boto3로 Amazon Bedrock의 Converse API를 부른다. ADK가 모델에 보내는 요청 하나(대화, 시스템 지시, 도구 선언)가 Converse 호출 하나가 되고, 그 답(글과 도구 호출)이 ADK의 응답 하나가 된다. 스트리밍은 하지 않는다. 모델은 허브의 `MODEL_ID`, 리전은 `HUB_REGION`이다. 실행 역할이 부를 수 있는 모델이 이것 하나다.

## 버전과 크기

`google-adk`는 2.14.1로 고정했다. 2026-11-22의 최신은 2.15.0이었다. 2.15.0도 이 에이전트의 다섯 줄로는 검사를 통과하고 묶음도 한도 안이었지만(압축 46,329,030바이트), `watchdog>=7`을 요구한다. `quality_agent`의 시험이 쓰는 `strands-agents==1.65.0`은 `watchdog<7`을 요구하므로, 이 리포의 시험 환경 하나에 둘을 함께 둘 수 없었다. 2.14.1은 둘 다와 맞고, 모든 Runtime이 쓰는 `aws-opentelemetry-distro==0.24.0`과도 맞는다(둘이 받는 OpenTelemetry가 1.45.2로 같다). 시험 환경도 같은 판을 쓴다(`pyproject.toml`).

2026-11-22에 이 리포의 `requirements.txt` 그대로 심사의 규칙대로 확인한 값이다.

- 검사: `pip-audit` 2.10.1(`PIP_ONLY_BINARY=:all:`)이 `No known vulnerabilities found`.
- 묶음: `uv` 0.10.8로 Runtime의 플랫폼용 wheel을 받아 배포 build와 같은 방식(`deploy_build.package`)으로 묶으면 압축 46,291,484바이트, 풀면 113,794,908바이트(파일 7,260개)다. AgentCore 개발자 안내서("Quotas for Amazon Bedrock AgentCore"의 Runtime 표, 2026-11-22에 읽었다)는 직접 코드 배포의 묶음 한도를 압축 250 MB, 풀어서 750 MB로 적는다. 이 한도는 여기서는 확인하지 않았다.

## 허브에서 받는 통제

에이전트 게이트웨이에 target(`DocsAdk`)이 있으므로 다른 에이전트와 같이 진입의 통제를 받는다. 들어오는 요청은 진입 정책(`entry_permit_docs_adk`), 비밀값 검사(`guard_secret_docs_adk`), 켜진 전사 정책, 붙어 있으면 커스텀 가드레일을 지난다. 멈춤 명령(`stop.sh`)도 닿는다. 다른 에이전트와 같은 코드가 그렇게 하는 것이다. 이 에이전트로 본 것은 진입 정책과 비밀값 검사(아래 시험 호출의 200과 403), 그리고 2026-11-22의 운영 확인(`make e2e-ops`)에서 본 전사 정책이다. 그 실행에서는 `guard_prompt`를 적용 모드로 켜고 커스텀 가드레일을 붙인 허브에 이 에이전트를 올렸다. 심사는 `SUCCEEDED`(517초, Scan 180초)였고, 그 Approve가 건 `guard_prompt_docs_adk`가 `ACTIVE`였다. 숨은 지시가 든 요청은 첫 호출부터 403이었고, 기록에 남은 본문의 앞부분은 `Request Denied: Gateway Target request not allowed due to policy enforcement [Policy evaluation denied due to guar`였다(정책 엔진의 거부이고, 정책 이름은 앞부분만 남았다). 이 거부는 `guard_prompt_docs_adk`의 것으로 본다. 그때 함께 걸린 비밀값 검사는 같은 요청을 막지 않았고(같은 실행에서 기록 모드일 때 `release_review`가 이 요청에 200이었다), 커스텀 가드레일의 거부는 본문이 다르다(`Blocked by the company guardrail (interceptor).`). 다른 에이전트가 멈춘 동안 `What is our standard for versioning an API?`에 200이었다. 커스텀 가드레일이 이 에이전트의 요청을 막거나 답을 가리는 것과 멈춤 명령은 이 에이전트로는 보지 않았다. 도구는 허브를 지나지 않으므로 도구 게이트웨이의 정책과 도구 호출 수의 메트릭에는 이 에이전트가 없다.

## 2026-11-22의 실행에서 본 것

`us-west-2`, 접두어 `hub`, 모델은 기본값(`us.anthropic.claude-haiku-4-5-20251001-v1:0`)이다. 빈 계정에서 `AUTO_APPROVE=1 make deploy seed preload`를 한 번 돌렸다.

- 심사는 `SUCCEEDED`였고 364초 걸렸다. Read 1초, Scan 44초(CodeBuild의 `pip-audit`도 통과했다), Grant 3초, Deploy 258초, Entry 35초, TestCall 8초, Approve 15초다. Grant는 도구 정책을 하나도 만들지도 지우지도 않았다(`toolPolicies`와 `removedToolPolicies`가 빈 목록).
- 배포 build가 올린 코드 묶음은 46,294,955바이트였고, 새 Runtime이 `READY`가 되기까지 231초였다. Runtime은 다른 에이전트와 같은 `opentelemetry-instrument main.py`로 떴고 ADK 에이전트가 그 아래에서 답했다.
- 시험 호출은 보통 질문(`What is the spec of part P-100?`)에 200, 예시 access key가 든 질문에 403이었다. 심사의 상태에 남은 보통 질문의 답(앞의 400자)은 `I don't have a tool available to look up part specifications. My role is to help answer questions about the company's design standards`로 시작했다(심사는 상태만 본다).
- 승인된 뒤 에이전트 게이트웨이로 `What is our standard for versioning an API?`를 묻자 4.2초 만에 200이 왔다. 답은 API 버전 표준의 ID와 세 규칙(경로의 주 버전 `/v1/...`, 깨지는 변경에는 새 주 버전, 앞 버전을 6개월 더 제공)이었고 `tools_used`는 `["find_standard"]`였다. 표준의 ID는 그 실행 뒤에 이름만 바꿨다(지금은 `STD-01`부터).
- Runtime의 로그 그룹에 오류 줄이나 traceback은 없었다. 경고 줄은 넷이었다. 둘은 OpenTelemetry의 로그 계측이 LoggingHandler를 붙이지 않았다는 줄(`Skipping installation of LoggingHandler ...`)이고, 둘은 `Invalid HTTP request received.`다. 이 줄들이 무엇 때문인지는 알아보지 않았다.

## 로컬에서 시험하기

```bash
uv run pytest tests/test_docs_adk.py -q
```

가짜 Bedrock 클라이언트로 ADK의 runner, 도구, 모델 클래스를 실제로 돌린다. AWS를 부르지 않는다.
