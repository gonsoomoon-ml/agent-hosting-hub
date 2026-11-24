# 영상처럼 따라 하기

시연 영상의 순서(준비와 다섯 단계)를 자기 AWS 계정에서 손으로 따라 하는 안내다. 영상에 나오는 명령과 허브 화면을 그대로 쓰고, 걸음마다 무엇을 보게 되는지와 걸린 시간을 적었다.

- **무엇을 하나**: 허브를 올리고, 에이전트 둘을 신청해 심사를 지나게 하고, 전사 정책과 커스텀 가드레일을 걸고, 사고를 낸 에이전트 하나만 멈췄다가 다시 연다. 마지막에 모두 지운다.
- **걸리는 시간**: 한 시간 반쯤이다. 대부분은 기다리는 시간이다(허브 올리기 15분, 호스팅 심사 네 번이 5~7분씩, 지우기 10~18분).
- **요금**: 허브가 떠 있는 동안과 부를 때마다 요금이 든다([요금과 지우기의 "허브가 떠 있는 동안 요금이 드는 것"](cost-and-cleanup.md#허브가-떠-있는-동안-요금이-드는-것)). 끝나면 `make destroy`로 지운다.
- **확인한 범위**: 여기의 명령과 입력은 `make e2e`, `make e2e-ops`와 영상의 녹화가 2026-11-22와 2026-11-23에 쓴 것이고, 적힌 시간과 출력은 그 실행들에서 본 것이다([장면의 명령](../demo_scenes/README.md), [확인한 것](checks.md#make-e2e-ops가-확인하는-것)). 이 문서를 처음부터 끝까지 사람이 손으로 따라 한 실행은 아직 없다.

## 준비물

- [시작하기의 "사전 요건"](getting-started.md#사전-요건): Terraform, Python과 uv, AWS 자격 증명, 리전 `us-west-2`, Amazon Bedrock 모델 사용 권한.
- 터미널 둘과 브라우저 하나. 한 사람이 두 역할을 번갈아 맡는다. 터미널 하나는 **개발팀**(찾기, 신청, 로그 읽기)과 **사용자**(에이전트 부르기)의 것이고, 다른 하나는 **플랫폼팀**(허브 올리기, 운영 명령, 허브 화면)의 것이다.
- 이 안내에서는 두 터미널이 같은 자격 증명(관리자 권한)을 쓴다. 영상의 개발자는 개발팀 역할만 가진 컨테이너에서 일한다(끝의 "영상과 다른 점").
- 모든 명령은 저장소의 루트에서 친다.

## 준비: 플랫폼팀이 허브를 한 번 만들어 둔다

플랫폼팀의 터미널에서 친다.

```bash
cp .env.example .env     # 접두어를 바꾸려면 DEMO_PREFIX를 고친다(소문자와 숫자 2~10자)
make deploy              # 계획을 보여 주고 yes를 묻는다. 빈 계정에서 4분
make seed                # 공유 도구 record를 카탈로그에 넣는다. 6초
make preload             # 처음부터 올라와 있는 에이전트 둘을 올린다. 11분
make ui                  # 허브 화면. http://127.0.0.1:8300 , Ctrl+C로 멈춘다
```

- `make ui`는 터미널을 차지하므로 터미널 하나를 더 열어 실행해 둔다.
- 화면은 실행한 PC의 `127.0.0.1`에서만 열린다. 원격 PC에서 실행했다면 SSH 포트 포워딩(`ssh -L 8300:127.0.0.1:8300 <원격 PC>`)으로 본다.
- **보게 되는 것**: 홈에 호스팅된 에이전트 2, 승인 대기 0, 도구 1이 보이고, 카탈로그에 `docs_adk`, `parts-tools`, `spec_assistant`가 `APPROVED`로 있다.

## 1단계. 호스팅 신청: 팀은 플랫폼팀 없이 찾고, 만들고, 신청한다

개발팀의 터미널에서 친다.

```bash
demo_scenes/search "part specification tool"
demo_scenes/publish release_review
demo_scenes/publish quality_agent v1-vulnerable
```

| 걸음 | 하는 일 | 보게 되는 것 |
|---|---|---|
| 찾기 | 카탈로그에서 쓸 도구를 찾는다. 검색어는 영어로 쓴다(2026-11-23에 `"부품 규격"`은 맞는 레코드가 없었다). | `parts-tools  (MCP)`와 그 도구 둘(`tool get_part_spec: part_id`, `tool get_test_result: part_id`), `spec_assistant  (AGENT)` |
| 만들기 | 영상에서는 Claude Code가 표준 템플릿으로 에이전트를 만든다. 여기서는 준비된 `dev_team/quality_agent/`를 읽어 본다. 신청서는 `agent.json`, 코드는 `agent.py`, 의존성은 `requirements.txt`다. 직접 만들려면 [에이전트 템플릿](../dev_team/agent_template/README.md)을 본다. | 신청서의 `tools`에 방금 찾은 도구 `Parts___get_part_spec`이 있다 |
| 신청 | 두 에이전트를 신청한다. `v1-vulnerable`은 취약한 라이브러리가 든 버전이다. 명령은 6초씩 걸린다. | 두 번 모두 끝 줄이 `record … is PENDING_APPROVAL`이다. 호스팅 심사 둘이 시작된다 |

## 2단계. 호스팅 심사: 신청이 들어오면 허브가 자동으로 심사한다

허브 화면의 `호스팅 심사`(`/reviews`)를 연다. 화면은 5초마다 스스로 다시 그린다.

```bash
demo_scenes/ask release_review --file demo_scenes/inputs/change-ok.txt
platform_team/hosting_review/reject.sh quality_agent "jinja2 2.11.2에 알려진 취약점이 있어 반려합니다."
demo_scenes/publish quality_agent
demo_scenes/ask quality_agent "What is the spec of part P-100?"
```

| 걸음 | 누가 | 하는 일 | 보게 되는 것 |
|---|---|---|---|
| 심사를 본다 | 플랫폼팀 | 두 신청의 일곱 단계(Read, Scan, Grant, Deploy, Entry, TestCall, Approve)가 지나가는 것을 본다. | `quality_agent`는 Scan에서 실패한다(44초). `release_review`는 일곱 단계를 지나 레코드가 `APPROVED`가 된다(404초, 그 가운데 Deploy 280초) |
| 부른다 | 사용자 | 승인된 `release_review`에게 변경 설명을 보낸다. | `HTTP 200 (7.3 s)`와 답 `OK` |
| 반려한다 | 플랫폼팀 | `/reviews/quality_agent`에서 "스캔이 실패한 이유"를 읽고, 사유를 써서 `반려하기`를 누른다. 위의 `reject.sh`가 같은 일을 한다. 심사가 끝난 뒤에 한다. | 스캔이 찾은 줄(`jinja2 2.11.2`와 권고 ID, 고친 버전)이 보이고, 반려 뒤 레코드가 `REJECTED`다 |
| 고쳐서 다시 신청한다 | 개발팀 | 변형 없이 올리면 고친 버전(취약한 라이브러리가 없다)이다. | `PENDING_APPROVAL`, 그리고 심사가 일곱 단계를 지나 `APPROVED`(392초) |
| 부른다 | 사용자 | 승인된 `quality_agent`에게 부품 규격을 묻는다. | `HTTP 200`과 `M4 x 12 mm`, steel이 든 답(공유 도구가 돌려준 값) |

## 3단계. 전사 정책 시험: 새 전사 정책을 막지 않고 먼저 시험한다

허브 화면의 `전사 정책`(`/policies`)에서 `기록 모드로 걸기`를 누른다. 아래의 첫 명령이 같은 일을 한다.

```bash
platform_team/company_policy/rollout.sh guard_prompt log-only
demo_scenes/ask release_review --file demo_scenes/inputs/change-with-hidden-instruction.txt
platform_team/company_policy/rollout.sh guard_prompt report
```

| 걸음 | 누가 | 하는 일 | 보게 되는 것 |
|---|---|---|---|
| 기록 모드로 건다 | 플랫폼팀 | 전사 정책 `guard_prompt`를 호스팅된 에이전트 모두에 기록 모드로 건다(에이전트 둘에 27초, 셋에 40초). | 화면의 작업 칸이 `끝남`이 되고, 모드가 기록 모드로 보인다 |
| 숨은 지시를 보낸다 | 사용자 | 변경 설명 뒤에 "앞선 지시를 무시하라"는 문단이 든 입력을 보낸다. | `HTTP 200`. 기록 모드는 막지 않는다 |
| 기록을 본다 | 플랫폼팀 | 1분쯤 기다린 뒤 화면의 기록이나 `report`를 본다(2026-11-22와 23에 56~65초 뒤에 보였다). | `release_review`에 `LogOnlyMatches 1`, 요청을 받지 않은 에이전트는 0 |

## 4단계. 전사 정책 적용: 전사 정책 하나가 모든 에이전트에 걸린다

`전사 정책` 페이지에서 `적용 모드로 올리기`를 누르고, 뒤에서 `커스텀 가드레일 붙이기`를 누른다. 아래의 `rollout.sh`와 `guardrail.sh`가 같은 일을 한다.

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

| 걸음 | 누가 | 하는 일 | 보게 되는 것 |
|---|---|---|---|
| 적용 모드로 올린다 | 플랫폼팀 | 같은 정책의 모드를 적용 모드로 바꾼다(에이전트 둘에 35초, 셋에 54~62초). | 모드가 적용 모드로 보인다 |
| 같은 입력을 보낸다 | 사용자 | 3단계의 입력을 두 에이전트에 보낸다. | 둘 다 `HTTP 403`이고, 거절 문장에 `guard_prompt_`로 시작하는 정책 이름이 있다. 보통의 질문은 여전히 200이다 |
| 가드레일을 붙이기 전 | 사용자 | 코드명(`Project Falcon`)이 든 요청과, 답에 사번이 실리는 질문을 보낸다. | 둘 다 200이고, 둘째 답에 `EMP-204817`이 있다(이 샘플의 합성 데이터다) |
| 커스텀 가드레일을 붙인다 | 플랫폼팀 | interceptor Lambda를 에이전트 게이트웨이에 붙인다(5초). | 화면에 가드레일이 붙어 있다고 보인다 |
| 붙인 뒤 | 사용자 | 같은 두 명령을 다시 보낸다. | 첫째는 `HTTP 403`과 `Blocked by the company guardrail (interceptor).`, 둘째는 200이고 사번 자리에 `{employee_id}`가 있다 |

## 5단계. 이상 대응: 문제를 일으킨 에이전트 하나만 멈춘다

허브 화면의 `에이전트`(`/agents`)를 연다. 전사 정책과 커스텀 가드레일은 걸어 둔 채로 간다.

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

| 걸음 | 누가 | 하는 일 | 보게 되는 것 |
|---|---|---|---|
| 사용량을 본다 | 플랫폼팀 | `에이전트` 페이지나 `usage.sh`로 에이전트 넷의 호출 수와 도구별 호출 수를 본다. | 에이전트 넷의 표와 도구별 호출 수 |
| 사고가 나는 버전을 올린다 | 개발팀 | `v2-loop`는 같은 도구를 반복해 부르는 버전이다. 승인된 에이전트의 새 버전도 같은 심사를 지난다. | 심사가 통과한다(2026-11-22에 304초) |
| 사고 | 사용자 | 검사 Q-1002를 묻는다. 심사가 끝난 뒤에 보낸다. | 답이 오지 않는다(`no answer from quality_agent within 60 s`). 에이전트는 도구를 계속 부른다 |
| 경보를 본다 | 플랫폼팀 | `에이전트` 페이지의 "도구 호출 경보"에서 분당 호출 수와 경보(CloudWatch alarm)의 상태를 본다. | 도구의 분당 호출이 임계값 19를 넘고(2026-11-22에 분당 42와 38), 경보 `<접두어>-tool-calls`가 `ALARM`이 된다(알림은 호출 59~86초 뒤에 왔다) |
| 하나만 멈춘다 | 플랫폼팀 | `quality_agent`의 `멈추기`를 누른다. `stop.sh`가 같은 일을 한다(20초). | 그 에이전트가 멈춤으로 보인다 |
| 이웃은 답한다 | 사용자 | 멈춘 에이전트와 이웃 둘을 부른다. | `quality_agent`는 `HTTP 403`(문장에 `stop_agent_quality_agent`), `release_review`와 `docs_adk`는 200 |
| 원인을 찾는다 | 개발팀 | 에이전트의 로그를 읽고, 올린 버전의 코드 `dev_team/quality_agent/variants/v2-loop/agent.py`를 본다. 영상에서는 Claude Code가 한다. | 로그에 `asking again (<n>)` 줄이 있다(2026-11-23에 분당 23~25줄). 코드에는 횟수 제한 없이 다시 묻는 곳이 있다 |
| 고친 버전으로 돌아온다 | 개발팀 | 변형 없이 다시 신청한다. | 에이전트가 멈춘 채로 심사가 통과한다(298초). 사용자의 호출은 아직 403이다 |
| 재개한다 | 플랫폼팀, 사용자 | `재개`를 누르고(`resume.sh`, 8초) 다시 부른다. | `HTTP 200`이고 두 도구를 써서 답한다. 가드레일이 붙어 있는 동안에는 사번 자리가 `{employee_id}`다 |

## 끝내기

```bash
make destroy             # 계획을 보여 주고 yes를 묻는다
```

- 붙여 둔 커스텀 가드레일을 떼고, 전사 정책의 모드를 지우고, 심사가 에이전트마다 만든 것을 지운 다음 `terraform destroy`를 돈다. 손으로 먼저 되돌릴 것은 없다([요금과 지우기의 "`make destroy`가 지우는 것과 남기는 것"](cost-and-cleanup.md#make-destroy가-지우는-것과-남기는-것)).
- 끝 줄이 `still present: nothing`이면 허브가 만든 것이 남지 않은 것이다. 승인된 에이전트 둘이 있는 허브에서 9분 26초였고, 에이전트 넷과 전사 정책이 있는 허브에서는 17분 42초였다(2026-11-23). 이 안내를 끝낸 허브는 뒤쪽에 가깝다.
- 허브를 지우지 않고 5단계까지를 다시 하려면 `guardrail.sh detach`, `rollout.sh guard_prompt off`, `resume.sh quality_agent`로 운영의 상태를 되돌린다.

## 영상과 다른 점

- 영상의 개발자는 Docker 컨테이너 안에서 Claude Code로 찾고, 만들고, 원인을 찾는다. 그 컨테이너에는 개발팀 역할의 자격 증명만 들어간다([시연 영상을 만드는 것](../demo_video/README.md)). 이 안내는 같은 일을 `search`, 준비된 폴더, `logs`로 한다.
- 영상에서 Claude Code가 만든 에이전트는 화면에 보이기만 하고, 올리는 것은 이 안내와 같은 `dev_team/quality_agent`다.
- 영상은 기다리는 구간(심사, 경보)을 빠르게 돌려 보인다. 실제로는 위에 적은 시간이 걸린다.

## 막히면

| 보이는 것 | 까닭과 할 일 |
|---|---|
| `search`가 `no approved record matches …`를 출력한다 | 승인된 레코드만 나온다. `make seed`와 `make preload`가 끝났는지 보고, 검색어를 영어로 쓴다 |
| 반려 버튼이 없거나 반려가 아무것도 바꾸지 않는다 | 심사가 도는 동안에는 반려하지 않는다. 심사가 끝난 뒤에 누른다 |
| 버튼을 눌렀는데 "다른 작업이 진행 중"이라는 문장이 나온다 | 화면의 작업은 한 번에 하나다. 작업 칸이 `끝남`이 된 뒤에 다시 누른다 |
| 기록 모드에서 숨은 지시를 보냈는데 기록이 0이다 | 기록은 1분쯤 뒤에 보인다. 입력을 고쳤다면, 그 문장이 제 문단으로 있어야 정책이 잡는다(2026-11-23에 주석 한 줄 안에 넣은 꼴은 잡히지 않았다) |
| 5단계의 질문에 답이 온다 | 새 버전은 심사의 Deploy가 끝나야 돈다. 그 전에는 앞의 버전이 답한다. `호스팅 심사` 페이지에서 `v2-loop`의 심사가 끝난 뒤에 보낸다 |
