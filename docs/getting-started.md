# 시작하기

[README](../README.md)로 돌아가기

허브를 올리기 전에 갖출 것과, 올리고 지우는 일곱 명령을 적습니다.

## 사전 요건

- Terraform 1.9 이상, Python 3.12 이상과 [uv](https://docs.astral.sh/uv/), bash
- AWS 자격 증명. 허브는 IAM 역할, 정책 엔진, 게이트웨이, Lambda, CodeBuild, Step Functions, S3 bucket 등을 만듭니다. 관리자 권한의 자격 증명으로 확인했습니다.
- 리전 `us-west-2`. 셸의 기본 리전이 다르면 `AWS_REGION=us-west-2`를 줍니다.
- Amazon Bedrock 모델 사용 권한. 기본 모델은 추론 프로파일 `us.anthropic.claude-haiku-4-5-20251001-v1:0`입니다.
- trace를 보려면 계정의 CloudWatch Transaction Search를 켜 둡니다. 계정에서 한 번 하는 설정이고, 허브는 이것을 켜지도 끄지도 않습니다. [모니터링](../platform_team/agent_monitoring/README.md#무엇이-어디에-남는가)

이 저장소의 첫 공개 버전으로 올린 허브가 있으면, 그 버전의 코드로 `make destroy`를 돌려 지운 뒤 지금의 코드로 다시 올립니다.

## `.env`

`.env.example`을 `.env`로 복사하고 세 값을 정합니다. `make`와 모든 명령이 이 파일을 읽습니다.

| 이름 | 뜻 | 기본값 |
|---|---|---|
| `AWS_REGION` | 리전 | `us-west-2` |
| `DEMO_PREFIX` | 접두어. 허브가 만드는 자원의 이름 앞에 붙습니다 | `hub` |
| `MODEL_ID` | 에이전트가 부르는 모델 | 위의 추론 프로파일 |

- 한 줄에 `이름=값`으로 씁니다. 따옴표, `export`, `=` 앞뒤의 빈칸은 쓰지 않습니다.
- `.env`에서 읽는 것은 이 세 줄뿐입니다. 자격 증명을 적어 두어도 쓰이지 않습니다.
- 값은 `make`의 명령줄(`make deploy DEMO_PREFIX=demo`), `.env`, 셸의 환경 변수, 기본값의 순서로 찾습니다.
- 접두어는 소문자로 시작하는 2~10자의 소문자와 숫자입니다(`hub`, `demo2`). `harness`는 쓸 수 없습니다. AgentCore가 harness의 Runtime 이름에 쓰는 말이라 이름이 겹칩니다.
- 에이전트가 올라와 있는 허브에서 `MODEL_ID`를 바꿔도 이미 있는 에이전트는 옛 모델을 씁니다. Runtime 에이전트는 새 버전을 제출하면 바뀌고, harness(`spec_assistant`)는 허브를 지우고 다시 올려야 바뀝니다. 코드가 그렇게 하고, AWS에서 모델을 바꿔 본 적은 없습니다.

## 일곱 명령

| 순서 | 명령 | 하는 일 | 걸린 시간 |
|---|---|---|---|
| 1 | `make deploy` | 허브의 기반 자원을 배포합니다. 계획을 보여 주고 `yes`를 묻습니다. `AUTO_APPROVE=1`이면 묻지 않습니다. | 빈 계정에서 약 4분(234~235초). 다시 올리면 약 10초 |
| 2 | `make seed` | 공유 도구 레코드(`parts-tools`)를 카탈로그에 넣고 승인합니다. 개발자의 첫 검색이 이것을 찾습니다. | 6초 |
| 3 | `make preload` | 에이전트 둘을 미리 올려 둡니다(아래 "미리 올려 둔 에이전트 둘"). 이미 있는 것은 그대로 둡니다. | 11~14분(660~810초). 다시 돌리면 3~8초 |
| 4 | `dev_team/agent_template/publish.sh dev_team/<에이전트> [변형]` | 개발팀이 코드를 제출 버킷에 올리고 신청서를 카탈로그에 쓰고 승인을 요청합니다. 호스팅 심사가 자동으로 시작합니다. 개발팀 역할(`<prefix>-dev-role`)의 권한이면 됩니다. | 명령은 6초. 심사는 통과할 때 약 6분(356~387초), Scan에서 떨어질 때 31~38초 |
| 5 | `make e2e` | 흐름 1(호스팅)을 처음부터 끝까지 확인합니다([확인한 것](checks.md#make-e2e가-확인하는-것)). 기록은 `e2e_checks/last-run.log`에 남습니다. | 약 14분(853~865초) |
| 6 | `make e2e-ops` | 흐름 2(운영)를 처음부터 끝까지 확인합니다([확인한 것](checks.md#make-e2e-ops가-확인하는-것)). `make e2e`가 끝난 허브에서 돌고, 그 안에서 `make preload`를 부릅니다. 기록은 `e2e_checks/last-run-ops.log`에 남습니다. | 약 33~35분(1956~2090초). 같은 허브에서 다시 돌리면 약 22분(1305초) |
| 7 | `make destroy` | 허브가 만든 것을 모두 지웁니다([요금과 지우기](cost-and-cleanup.md#make-destroy가-지우는-것과-남기는-것)). 계획을 보여 주고 `yes`를 묻습니다. | 에이전트 둘이면 약 10분(566~595초), 넷이면 약 18분(1062~1081초) |

- 시간은 2026-11-22와 2026-11-23의 실행(`us-west-2`, 접두어 `hub`)에서 잰 것입니다.
- `make deploy`와 `make destroy`는 `AUTO_APPROVE=1`로만 돌렸습니다. `yes`를 묻는 대화와, 4번과 같은 일을 하는 `make publish AGENT=<에이전트>`는 확인하지 않았습니다.
- `make test`는 단위 테스트입니다. AWS를 부르지 않습니다.

## 미리 올려 둔 에이전트 둘

`make preload`가 올립니다(`make deploy`와 `make seed` 뒤에). 둘 다 `dev_team/preloaded_agents/`에 있고, 허브에서 받는 대우가 다릅니다.

| | [docs_adk](../dev_team/preloaded_agents/docs_adk/README.md) | [spec_assistant](../dev_team/preloaded_agents/spec_assistant/README.md) |
|---|---|---|
| 무엇 | Google ADK로 만든, 사내 설계 표준을 묻는 질문에 답하는 에이전트. 코드가 있습니다. | 부품의 사양과 시험 결과를 묻는 질문에 답하는 AgentCore managed harness. 모델, 지시문, 쓸 도구로만 정의되고 코드가 없습니다. |
| 올라가는 길 | 다른 팀의 에이전트와 같이 제출되고 같은 심사를 거칩니다. | 심사가 건너뜁니다(코드가 없습니다). `make preload`가 플랫폼팀의 자격 증명으로 실행 역할, 도구 정책, harness, 승인된 레코드를 만듭니다. |
| 부르는 곳 | 에이전트 게이트웨이(target `DocsAdk`) | AgentCore의 `InvokeHarness`. 에이전트 게이트웨이 뒤에 없습니다. |
| 진입의 통제 | 받습니다. 진입 정책, 비밀값 검사, 전사 정책, 커스텀 가드레일을 지나고, 멈춤 명령(`stop.sh`)이 닿습니다. | 받지 않습니다. 진입 target이 없어 전사 정책과 커스텀 가드레일이 닿지 않고, 멈춤 명령도 이 에이전트를 거부합니다. |
| 도구 | 에이전트 안에서 도는 함수 하나(`find_standard`). 허브를 지나지 않습니다. | 도구 게이트웨이의 공유 도구 둘. 실행 역할에 걸린 permit 둘만큼만 부를 수 있습니다. |

- `make preload`를 다시 돌려도 이미 있는 harness는 그대로입니다. `agent.json`이나 `MODEL_ID`를 바꿨다면 `make destroy`로 허브를 지우고 다시 올립니다.
- 2026-11-22의 실행에서 `docs_adk`는 심사를 통과해(364초) 설계 표준의 글로 답했고, `spec_assistant`는 `What is the spec of part P-100?`에 `M4 x 12 mm`가 든 답을 했습니다. 자세한 것은 두 에이전트의 문서에 있습니다.
