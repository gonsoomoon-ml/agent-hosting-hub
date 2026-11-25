# 영상처럼 따라 하기

시연 영상의 순서(준비와 다섯 단계)를 자기 AWS 계정에서 손으로 따라 하는 안내입니다. 영상에 나오는 명령과 허브 화면을 그대로 씁니다.

- **무엇을 하나**: 허브를 올리고, 에이전트 둘을 신청해 심사를 지나게 하고, 전사 정책과 커스텀 가드레일을 걸고, 사고를 낸 에이전트 하나만 멈췄다가 다시 엽니다. 마지막에 모두 지웁니다.
- **걸리는 시간**: 한 시간 반쯤이고, 대부분은 기다리는 시간입니다. 허브 올리기 15분, 호스팅 심사 네 번이 5~7분씩, 지우기 10~18분입니다.
- **요금**: 허브가 떠 있는 동안과 부를 때마다 듭니다([요금과 지우기](cost-and-cleanup.md#허브가-떠-있는-동안-요금이-드는-것)).
- **확인한 범위**: 명령, 시간, 출력은 2026-11-22와 2026-11-23의 `make e2e`, `make e2e-ops`와 영상의 녹화에서 쓰고 본 것입니다([장면의 명령](../demo_scenes/README.md), [확인한 것](checks.md#make-e2e-ops가-확인하는-것)). 이 안내를 처음부터 끝까지 손으로 따라 한 실행은 아직 없습니다.

## 준비물

- [시작하기의 "사전 요건"](getting-started.md#사전-요건)에 적힌 도구, 자격 증명, 리전, 모델 사용 권한.
- 터미널 둘과 브라우저 하나. 한 터미널은 **개발팀**과 **사용자**의 것이고, 다른 터미널은 **플랫폼팀**의 것입니다.
- 두 터미널은 같은 자격 증명(관리자 권한)을 씁니다. 영상의 개발자는 개발팀 역할만 가진 컨테이너에서 일합니다.
- 모든 명령은 저장소의 루트에서 칩니다.

## 준비: 플랫폼팀이 허브를 한 번 만들어 둡니다

플랫폼팀의 터미널에서 칩니다.

```bash
cp .env.example .env     # 접두어를 바꾸려면 DEMO_PREFIX를 고칩니다(소문자와 숫자 2~10자)
make deploy              # 계획을 보여 주고 yes를 묻습니다. 빈 계정에서 4분
make seed                # 공유 도구 레코드를 카탈로그에 넣습니다. 6초
make preload             # 에이전트 둘을 미리 올려 둡니다. 11분
make ui                  # 허브 화면. http://127.0.0.1:8300 , Ctrl+C로 멈춥니다
```

- `make ui`는 터미널을 차지하므로 터미널을 하나 더 열어 실행해 둡니다.
- 화면은 실행한 PC의 `127.0.0.1`에서만 열립니다. 원격 PC라면 `ssh -L 8300:127.0.0.1:8300 <원격 PC>`로 봅니다.
- **보게 되는 것**: 홈에 호스팅된 에이전트 2, 승인 대기 0, 도구 1. 카탈로그에 `docs_adk`, `parts-tools`, `spec_assistant`가 `APPROVED`로 있습니다.

## 1단계. 호스팅 신청: 팀은 플랫폼팀 없이 찾고, 만들고, 신청합니다

개발팀의 터미널에서 칩니다.

```bash
demo_scenes/search "part specification tool"
demo_scenes/publish release_review
demo_scenes/publish quality_agent v1-vulnerable
```

| 걸음 | 보게 되는 것 |
|---|---|
| 쓸 도구를 찾습니다. 검색어는 영어로 씁니다. | `parts-tools  (MCP)`와 그 도구 둘(`tool get_part_spec: part_id`, `tool get_test_result: part_id`), `spec_assistant  (AGENT)` |
| 준비된 `dev_team/quality_agent/`의 `agent.json`, `agent.py`, `requirements.txt`를 읽어 봅니다. 직접 만들려면 [에이전트 템플릿](../dev_team/agent_template/README.md)을 봅니다. | 신청서의 `tools`에 방금 찾은 `Parts___get_part_spec`이 있습니다 |
| 두 에이전트를 신청합니다. `v1-vulnerable`은 취약한 라이브러리가 든 버전입니다. | 6초씩 걸리고, 끝 줄이 `record … is PENDING_APPROVAL`입니다. 심사 둘이 시작됩니다 |

## 2단계. 호스팅 심사: 신청이 들어오면 허브가 자동으로 심사합니다

허브 화면의 `호스팅 심사`(`/reviews`)를 엽니다. 화면은 5초마다 다시 그립니다.

```bash
demo_scenes/ask release_review --file demo_scenes/inputs/change-ok.txt
platform_team/hosting_review/reject.sh quality_agent "jinja2 2.11.2에 알려진 취약점이 있어 반려합니다."
demo_scenes/publish quality_agent
demo_scenes/ask quality_agent "What is the spec of part P-100?"
```

| 누가 | 걸음 | 보게 되는 것 |
|---|---|---|
| 플랫폼팀 | 두 신청이 일곱 단계(Read, Scan, Grant, Deploy, Entry, TestCall, Approve)를 지나는 것을 봅니다. | `quality_agent`는 Scan에서 실패합니다(44초). `release_review`는 약 7분(404초) 뒤에 `APPROVED`입니다 |
| 사용자 | `APPROVED`가 된 `release_review`에게 변경 설명을 보냅니다. | `HTTP 200 (7.3 s)`와 답 `OK` |
| 플랫폼팀 | 심사가 끝난 뒤 `/reviews/quality_agent`에서 "스캔이 실패한 이유"를 읽고, 사유를 써서 `반려하기`를 누릅니다. `reject.sh`가 같은 일을 합니다. | 스캔이 찾은 줄(`jinja2 2.11.2`와 권고 ID, 고친 버전). 레코드는 `REJECTED`가 됩니다 |
| 개발팀 | 변형 없이 다시 신청합니다. 고친 버전입니다. | `PENDING_APPROVAL`, 약 7분(392초) 뒤에 `APPROVED` |
| 사용자 | `APPROVED`가 된 `quality_agent`에게 부품 규격을 묻습니다. | `HTTP 200`과 공유 도구가 돌려준 `M4 x 12 mm`, steel |

## 3단계. 전사 정책 시험: 새 전사 정책을 막지 않고 먼저 시험합니다

허브 화면의 `전사 정책`(`/policies`)에서 `기록 모드로 걸기`를 누릅니다. 첫 명령이 같은 일을 합니다.

```bash
platform_team/company_policy/rollout.sh guard_prompt log-only
demo_scenes/ask release_review --file demo_scenes/inputs/change-with-hidden-instruction.txt
platform_team/company_policy/rollout.sh guard_prompt report
```

| 누가 | 걸음 | 보게 되는 것 |
|---|---|---|
| 플랫폼팀 | `guard_prompt`를 호스팅된 에이전트 모두에 기록 모드로 겁니다(에이전트 둘에 27초, 셋에 40초). | 작업 칸이 `끝남`이 되고, 모드가 기록 모드로 보입니다 |
| 사용자 | "앞선 지시를 무시하라"는 문단이 든 입력을 보냅니다. | `HTTP 200`. 기록 모드는 막지 않습니다 |
| 플랫폼팀 | 1분쯤 뒤 화면의 기록이나 `report`를 봅니다(56~65초 뒤에 보였습니다). | `release_review`에 `LogOnlyMatches 1`, 다른 에이전트는 0 |

## 4단계. 전사 정책 적용: 전사 정책 하나가 모든 에이전트에 걸립니다

`전사 정책` 페이지에서 `적용 모드로 올리기`를, 뒤에서 `커스텀 가드레일 붙이기`를 누릅니다. `rollout.sh`와 `guardrail.sh`가 같은 일을 합니다.

```bash
platform_team/company_policy/rollout.sh guard_prompt active
demo_scenes/ask release_review --file demo_scenes/inputs/change-with-hidden-instruction.txt
demo_scenes/ask docs_adk --file demo_scenes/inputs/change-with-hidden-instruction.txt

demo_scenes/ask quality_agent "Summarise the schedule of Project Falcon for part P-100."
demo_scenes/ask quality_agent "What was the result of inspection Q-1001, and what is the specification of the part it inspected?"
platform_team/custom_guardrail/guardrail.sh attach
demo_scenes/ask quality_agent "Summarise the schedule of Project Falcon for part P-100."
demo_scenes/ask quality_agent "What was the result of inspection Q-1001, and what is the specification of the part it inspected?"
```

| 누가 | 걸음 | 보게 되는 것 |
|---|---|---|
| 플랫폼팀 | 같은 정책을 적용 모드로 올립니다(에이전트 둘에 35초, 셋에 54~62초). | 모드가 적용 모드로 보입니다 |
| 사용자 | 3단계의 입력을 두 에이전트에 보냅니다. | 둘 다 `HTTP 403`이고, 거절 문장에 `guard_prompt_`로 시작하는 정책 이름이 있습니다. 보통의 질문은 200입니다 |
| 사용자 | 가드레일을 붙이기 전에, 코드명(`Project Falcon`)이 든 요청과 답에 사번이 실리는 질문을 보냅니다. | 둘 다 200이고, 둘째 답에 합성 데이터의 사번 `EMP-204817`이 있습니다 |
| 플랫폼팀 | interceptor Lambda를 에이전트 게이트웨이에 붙입니다(5초). | 가드레일이 붙어 있다고 보입니다 |
| 사용자 | 같은 두 명령을 다시 보냅니다. | 첫째는 `HTTP 403`과 `Blocked by the company guardrail (interceptor).`, 둘째는 200이고 사번 자리에 `{employee_id}` |

## 5단계. 이상 대응: 문제를 일으킨 에이전트 하나만 멈춥니다

허브 화면의 `에이전트`(`/agents`)를 엽니다. 전사 정책과 커스텀 가드레일은 걸어 둔 채로 갑니다.

```bash
platform_team/agent_monitoring/usage.sh
demo_scenes/publish quality_agent v2-loop
demo_scenes/ask quality_agent "What is the result of inspection Q-1002?" --timeout 60
platform_team/agent_stop/stop.sh quality_agent
demo_scenes/ask quality_agent "What is the spec of part P-100?"
demo_scenes/ask release_review --file demo_scenes/inputs/change-ok.txt
demo_scenes/ask docs_adk "What is our standard for versioning an API?"
demo_scenes/logs quality_agent
demo_scenes/publish quality_agent
platform_team/agent_stop/resume.sh quality_agent
demo_scenes/ask quality_agent "What was the result of inspection Q-1001, and what is the specification of the part it inspected?"
```

| 누가 | 걸음 | 보게 되는 것 |
|---|---|---|
| 플랫폼팀 | `에이전트` 페이지나 `usage.sh`로 사용량을 봅니다. | 에이전트 넷의 호출 수와 도구별 호출 수 |
| 개발팀 | 같은 도구를 반복해 부르는 버전 `v2-loop`를 올립니다. 승인된 에이전트의 새 버전도 같은 심사를 지납니다. | 약 5분(304초) 뒤에 심사가 통과합니다 |
| 사용자 | 심사가 끝난 뒤 검사 Q-1002를 묻습니다. | `no answer from quality_agent within 60 s`. 에이전트는 도구를 계속 부릅니다 |
| 플랫폼팀 | `에이전트` 페이지의 "도구 호출 경보"를 봅니다. | 분당 호출이 임계값 19를 넘고(분당 42와 38), 경보 `<접두어>-tool-calls`가 `ALARM`입니다. 알림은 호출 59~86초 뒤에 왔습니다 |
| 플랫폼팀 | `quality_agent`의 `멈추기`를 누릅니다. `stop.sh`가 같은 일을 합니다(20초). | 그 에이전트가 멈춤으로 보입니다 |
| 사용자 | 멈춘 에이전트와 다른 에이전트 둘을 부릅니다. | `quality_agent`는 `HTTP 403`(문장에 `stop_agent_quality_agent`), `release_review`와 `docs_adk`는 200 |
| 개발팀 | 로그와 코드 `dev_team/quality_agent/variants/v2-loop/agent.py`를 읽어 원인을 찾습니다. | 로그에 `asking again (<n>)` 줄이 분당 23~25줄 있고, 코드에 횟수 제한 없이 다시 묻는 곳이 있습니다 |
| 개발팀 | 변형 없이 고친 버전을 다시 신청합니다. | 멈춘 채로 약 5분(298초) 뒤에 심사가 통과합니다. 사용자의 호출은 아직 403입니다 |
| 플랫폼팀, 사용자 | `재개`를 누르고(`resume.sh`, 8초) 다시 부릅니다. | `HTTP 200`, 두 도구를 쓴 답. 가드레일이 붙어 있으면 사번 자리는 `{employee_id}`입니다 |

## 끝내기

```bash
make destroy             # 계획을 보여 주고 yes를 묻습니다
```

- 손으로 먼저 되돌릴 것은 없습니다. `make destroy`가 가드레일을 떼고 전사 정책과 에이전트까지 지웁니다([요금과 지우기](cost-and-cleanup.md#make-destroy가-지우는-것과-남기는-것)).
- 끝 줄이 `still present: nothing`이면 남은 것이 없습니다. 에이전트 넷과 전사 정책이 있는 허브를 지우는 데 17분 42초가 걸렸습니다(2026-11-23). 이 안내를 끝낸 허브도 이와 비슷합니다.
- 지우지 않고 다시 하려면 `guardrail.sh detach`, `rollout.sh guard_prompt off`, `resume.sh quality_agent`로 되돌립니다.

## 영상과 다른 점

- 영상의 개발자는 개발팀 역할의 자격 증명만 든 Docker 컨테이너에서 Claude Code로 찾고, 만들고, 원인을 찾습니다([시연 영상을 만드는 것](../demo_video/README.md)). 이 안내는 같은 일을 `search`, 준비된 폴더, `logs`로 합니다.
- 영상에서 Claude Code가 만든 에이전트는 보이기만 하고, 올리는 것은 같은 `dev_team/quality_agent`입니다.
- 영상은 기다리는 구간(심사, 경보)을 빠르게 돌려 보입니다.

## 막히면

| 보이는 것 | 할 일 |
|---|---|
| `search`가 `no approved record matches …`를 출력합니다 | 승인된 레코드만 나옵니다. `make seed`와 `make preload`가 끝났는지 보고, 검색어를 영어로 씁니다 |
| 반려 버튼이 없거나 반려가 아무것도 바꾸지 않습니다 | 심사가 끝난 뒤에 누릅니다 |
| "다른 작업이 진행 중"이라는 문장이 나옵니다 | 화면의 작업은 한 번에 하나입니다. 작업 칸이 `끝남`이 된 뒤에 누릅니다 |
| 기록 모드의 기록이 0입니다 | 1분쯤 뒤에 다시 봅니다. 입력을 고쳤다면 숨은 지시가 제 문단으로 있어야 잡힙니다 |
| 5단계의 질문에 답이 옵니다 | 새 버전의 Deploy가 끝나기 전에는 앞의 버전이 답합니다. `v2-loop`의 심사가 끝난 뒤에 보냅니다 |
