# 커스텀 가드레일

회사의 형식이 정해진 규칙을 에이전트 게이트웨이에서 지키게 합니다. 발표하지 않은 프로젝트의 코드명이 든 요청과 답은 막고, 직원의 사번은 가립니다. 규칙은 Amazon Bedrock Guardrails의 guardrail 하나(`<prefix>-company-guardrail`)이고, 에이전트 게이트웨이(`<prefix>-agents`)의 interceptor Lambda(`<prefix>-guardrail`)가 모든 요청과 모든 답에 그 guardrail을 적용합니다(`ApplyGuardrail`).

## 개념도에서의 위치

[개념도](../../docs/hosting-hub-concept.png)의 ⑫ "전사 정책 설정, 이상 에이전트 차단"에서 플랫폼팀이 거는 것 가운데 하나입니다. "에이전트 게이트웨이" 상자 안의 "커스텀 가드레일"이고, 도구 게이트웨이에는 붙이지 않습니다.

## 무엇을 막고 무엇을 가리나

| 규칙(Terraform 변수) | 기본값 | 요청에서 | 답에서 |
|---|---|---|---|
| 금지어(`code_names`) | `Project Falcon` | 막습니다. 403과 `{"error": "Blocked by the company guardrail (interceptor)."}` | 막습니다(같은 403) |
| 사번(`employee_id_pattern`) | `EMP-\d{6}` | `{employee_id}`로 바꿔서 에이전트에 넘깁니다 | `{employee_id}`로 바꿔서 돌려줍니다 |

- 가리는 것은 정규식에 맞는 값뿐입니다. 사람의 이름처럼 형식이 없는 값은 가리지 않습니다.
- 요청은 본문 전체로 검사합니다. JSON이면 풀어 읽은 필드 이름과 글자 값을 모두 검사하므로, escape로 쓴 글(`\u0050roject Falcon`)도 찾습니다.
- 본문이 글자인 `prompt`를 가진 JSON 객체이면 `prompt`만 가리고 다른 필드는 온 그대로 넘깁니다. 그 밖의 본문은 본문 전체를 가립니다.
- 답은 에이전트가 보낸 본문 그대로 검사하므로, 에이전트가 한국어 글을 `\uXXXX`처럼 escape로 쓰면 낱말 필터가 찾지 못할 수 있습니다. 확인하지 않았습니다.
- Lambda의 로그에는 지점, 상태 코드, 막았는지, 가렸는지가 남고, 글은 남지 않습니다.

## 붙이고 떼는 명령

interceptor는 Terraform이 아니라 이 명령으로 이미 있는 게이트웨이에 붙입니다.

```
platform_team/custom_guardrail/guardrail.sh attach   # 에이전트 게이트웨이에 붙입니다
platform_team/custom_guardrail/guardrail.sh status   # 붙었는지, policy engine과 그 모드, target
platform_team/custom_guardrail/guardrail.sh detach   # 뗍니다
```

- 플랫폼팀의 자격 증명으로 돌고, 접두어와 리전은 `.env`에서 읽습니다([시작하기의 `.env`](../../docs/getting-started.md#env)).
- `attach`는 게이트웨이의 설정을 읽은 그대로 다시 넘기고 interceptor만 더합니다. 서비스 모델은 `UpdateGateway`가 주지 않은 선택 필드를 초기화한다고 적는데, 여기서 본 것은 interceptor 필드 하나입니다. policy engine과 target은 그대로 남았습니다.
- `attach`는 고친 뒤에 policy engine의 설정과 target의 이름들이 앞과 같은지 봅니다. 다르면 오류로 끝나고, 되돌리지는 않습니다.
- interceptor는 요청(`REQUEST`)과 답(`RESPONSE`) 두 지점에 걸리고, 요청의 헤더는 Lambda에 넘기지 않습니다.
- 이미 붙어 있으면 `attach`가, 이미 떼어져 있거나 허브가 없으면 `detach`가 아무것도 하지 않고 성공합니다.
- 게이트웨이를 고치는 사이에 심사나 반려가 target을 바꾸면, 고치기는 된 채로 `the agent gateway <이름> changed in the update`로 실패합니다. 그때는 `status`로 보고 같은 명령을 다시 돌리면 되고, 이 겹침은 해 보지 않았습니다.
- `attach`는 이 허브의 Lambda `<prefix>-guardrail`만 붙입니다. 게이트웨이의 역할이 부를 수 있는 Lambda가 이것 하나라서, 다른 것을 붙이면 모든 요청이 막힙니다.
- `make destroy`는 다른 무엇보다 먼저 interceptor를 떼므로, 게이트웨이가 지워진 Lambda를 가리키는 일이 없습니다.
- 2026-11-22의 실행에서 붙이기와 떼기는 5초씩 걸렸습니다.

## 규칙과 가드레일 바꾸기

- 기본 규칙은 `terraform/variables.tf`의 두 변수를 바꿔 `make deploy`를 다시 돌리면 바뀝니다. Terraform은 guardrail의 새 버전을 Lambda의 `GUARDRAIL_VERSION`에 건 뒤에 옛 버전을 지우므로, Lambda가 지워진 버전을 가리키는 때가 없습니다.
- 고객의 가드레일로 바꾸려면 `interceptor_lambda.py`의 `guard(text, source)`를 바꿉니다. `text`는 검사할 글, `source`는 `"INPUT"`이나 `"OUTPUT"`이고, `(막혔는가, 가린 뒤의 글)`을 돌려줍니다.
- 회사의 guardrail을 그대로 쓰려면 Lambda의 환경 변수 `GUARDRAIL_ID`와 `GUARDRAIL_VERSION`, 역할 `<prefix>-guardrail-role`의 `bedrock:ApplyGuardrail` 자원을 그 guardrail로 바꿉니다.

## 기본 제공 가드레일과 나눈 일

| | 기본 제공 가드레일 | 커스텀 가드레일 |
|---|---|---|
| 검사하는 것 | 프롬프트 공격(`guard_prompt_<에이전트>`), 비밀값(`guard_secret_<에이전트>`) | 금지어, 사번 |
| 만드는 방법 | 전사 정책의 설정 | guardrail과 그것을 부르는 Lambda의 코드 |
| 기록 모드 | 있습니다(`LOG_ONLY`) | 없습니다. 붙어 있는 동안 막고 가립니다 |
| 걸리는 곳 | 에이전트마다의 진입(policy engine) | 에이전트 게이트웨이의 모든 target |

기본 제공 가드레일은 [전사 정책](../company_policy/README.md)과 [호스팅 심사](../hosting_review/README.md)에 있습니다.

## Lambda가 실패하면

- interceptor Lambda가 오류를 내거나 제한 시간(8초)을 넘기면 에이전트 게이트웨이는 그 요청을 거부합니다. Lambda가 실패하는 동안에는 모든 에이전트로 가는 요청이 막힙니다.
- 경보 `<prefix>-guardrail-errors`는 Lambda의 `Errors`가 1분에 1 이상이면 알림 주제 `<prefix>-alerts`로 알립니다([모니터링](../agent_monitoring/README.md)).
- 권한 문제처럼 게이트웨이가 Lambda를 부르지도 못한 경우는 이 메트릭에 들지 않는다고 봅니다. 확인하지 않았습니다.

## 확인한 것과 하지 않은 것

2026-11-22와 2026-11-23의 운영 확인(`make e2e-ops`, `us-west-2`, 접두어 `hub`)에서 에이전트를 둔 게이트웨이에 붙이고 뗐습니다.

- 붙어 있는 동안 코드명이 든 요청은 두 에이전트에서 403이었고, 도구가 준 사번 `EMP-204817`은 답에서 `{employee_id}`로 가려졌습니다.
- 코드명이 줄바꿈 바로 뒤에 오는 요청도 403이었습니다(2026-11-23, `make e2e-ui`).
- 떼자 코드명이 든 요청이 다시 200이었습니다. 붙이고 떼는 동안 policy engine(`ENFORCE`)과 target은 그대로였습니다.
- 붙어 있는 동안에도 `make preload`의 심사가 target을 더했고, 그 시험 호출은 기대대로였습니다.
- 2026-11-22의 `make destroy` 뒤에는 guardrail, Lambda, 경보, 역할이 남지 않았습니다.

확인하지 않은 것:

- 스트리밍 응답. 답은 한 번에 받는 방식으로만 돌려 봤고, `attach`는 응답을 받는 방식(`responseInterceptionMode`)을 정하지 않습니다.
- 금지어의 대소문자와 다른 표기, 한국어 글, escape로 쓴 글, JSON이 아닌 본문.
- 가린 요청을 기본 제공 가드레일이 어떤 모양으로 보는지.
- 이 리포의 코드로 Lambda가 실패할 때의 거부, 그리고 경보가 울리는 것.
- interceptor가 붙어 있는 동안 규칙을 바꾸는 것.

## 요금

- interceptor가 붙어 있으면 호출마다 Lambda가 두 번 돌고 guardrail이 두 번 검사합니다. 2026-11-22에 읽은 Amazon Bedrock 요금 페이지는 이 guardrail의 낱말 필터와 정규식의 민감 정보 필터를 무료라고 적습니다.
- 경보는 CloudWatch 요금 페이지에 따르면 시간 단위로 매기고 무료 사용량이 있습니다. 요금은 확인하지 않았습니다.

## 파일

| 파일 | 역할 |
|---|---|
| `terraform/` | guardrail과 그 버전, Lambda와 그 역할, 로그 그룹(14일), 경보 |
| `interceptor_lambda.py` | Lambda 진입점(`handler`)과 `guard` |
| `guardrail_attach.py`, `guardrail.sh` | 붙이기, 떼기, 상태 읽기와 그 명령 |
