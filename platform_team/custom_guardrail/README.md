# 커스텀 가드레일

회사에는 형식이 정해진 규칙이 있다. 발표하지 않은 프로젝트의 코드명은 밖으로 나가면 안 되고, 직원의 사번도 나가면 안 된다. 이 폴더는 그 규칙을 Amazon Bedrock Guardrails의 guardrail 하나(`<prefix>-company-guardrail`)로 만들고, 에이전트 게이트웨이(`<prefix>-agents`)의 interceptor Lambda(`<prefix>-guardrail`)가 모든 요청과 모든 답에 그 guardrail을 적용하게 한다(`ApplyGuardrail`). interceptor는 Terraform이 아니라 명령(`guardrail.sh attach`)으로 이미 있는 게이트웨이에 붙인다.

## 개념도에서의 위치

⑫ "전사 정책 설정, 이상 에이전트 차단"에서 플랫폼팀이 거는 것 가운데 하나다. "에이전트 게이트웨이" 상자에 붙고, ⑦ "작업 요청, 요청 전달"의 요청과 그 답이 이 Lambda를 지난다. 도구 게이트웨이에는 붙이지 않는다.

## 무엇을 막고 무엇을 가리나

| 규칙(Terraform 변수) | 기본값 | 요청에서 | 답에서 |
|---|---|---|---|
| 금지어(`code_names`) | `Project Falcon` | 막는다. 403과 `{"error": "Blocked by the company guardrail (interceptor)."}` | 막는다(같은 403) |
| 사번(`employee_id_pattern`) | `EMP-\d{6}` | `{employee_id}`로 바꿔서 에이전트에 넘긴다 | `{employee_id}`로 바꿔서 돌려준다 |

가리는 것은 형식이 있는 값, 곧 정규식에 맞는 값뿐이다. 사람의 이름처럼 형식이 없는 값은 가리지 않는다. 금지어는 guardrail의 낱말 필터로 찾는다. 대소문자가 다르거나 띄어쓰기가 다른 표기를 어떻게 다루는지는 확인하지 않았다.

요청을 막을지는 본문 전체의 글로 정한다. 본문이 JSON이면 풀어 읽은 문서의 필드 이름과 글자 값을 모두(어느 깊이든, 문서의 순서대로) 한 줄에 하나씩 이어 검사한다. 그래서 escape로 쓴 글(`\u0050roject Falcon`)은 `Project Falcon`으로, `\n`은 줄바꿈으로 읽힌다. 숫자, `true`, `false`, `null`은 검사하지 않는다. JSON이 아닌 본문은 온 그대로 검사한다. 가리는 것은 JSON 객체인 본문의 글자인 `prompt`이고, `prompt`만 가린 모양으로 넘기고 다른 필드는 온 그대로 넘긴다. 그 밖의 본문(base64가 아니거나, JSON이 아니거나, 객체가 아니거나, 글자인 `prompt`가 없는 것)은 온 그대로를 가리고, 가렸으면 본문 전체를 가린 모양으로 넘긴다. guardrail은 먼저 막을지를 정하는 글을 검사한다. 가리는 글이 그 글과 다르고 첫 검사가 무엇인가 가렸을 때만 가리는 글을 한 번 더 검사하고, 그 검사에서 막히면 요청도 막는다. 2026-11-23의 실행에서 붙어 있는 동안, 코드명이 든 요청은 두 에이전트에서 `{"error": "Blocked by the company guardrail (interceptor)."}`와 함께 403이었고(`make e2e-ops`의 5번), 코드명이 줄바꿈 바로 뒤에 오는 요청(JSON 본문에서 `\n`)도 403이었다(`make e2e-ui`의 6번). 사번 질문의 답에는 `EMP-` 대신 `{employee_id}`가 있었다. escape로 쓴 글과 JSON이 아닌 본문은 보내 보지 않았다. 답은 에이전트가 보낸 글 그대로(직렬화된 본문 전체) 검사한다. 그래서 에이전트의 서버가 규칙의 글을 escape로 쓰면(예: 한국어 글을 `\uXXXX`로 쓰는 JSON) 낱말 필터가 그 글을 찾지 못할 수 있다. 확인하지 않았다.

본문이 글자가 아니거나 이벤트의 모양이 달라도 Lambda는 예외를 내지 않는다(예외를 내면 게이트웨이가 그 요청을 거부한다. 아래 "Lambda가 실패하면"). 바이트인 본문은 그 안의 UTF-8 글로, JSON 객체나 목록이나 숫자인 본문은 그 JSON 글로 읽은 뒤 위와 같이 검사한다. 이벤트의 `http`, `gatewayRequest`, `gatewayResponse`가 객체가 아니면 본문이 없는 호출로 보고 그대로 넘긴다. JSON 파서가 받지 못할 만큼 깊이 겹친 JSON 본문은 JSON이 아닌 본문처럼 온 그대로 검사한다. 이 처리가 2026-11-23의 실행에서 쓰였는지는 알 수 없다(Lambda의 로그에 본문의 모양은 남지 않는다). 그 실행에서 붙어 있는 동안의 호출은 모두 403(막음)이나 200이었고, Lambda가 실패할 때 오는 400은 없었다. Lambda의 로그에는 어느 지점(`REQUEST`, `RESPONSE`)인지, 답이면 에이전트의 답이 가진 상태 코드(`status`), 막았는지, 가렸는지만 남고 글은 남지 않는다. 이 동작은 코드와 단위 시험(`tests/test_interceptor.py`)이 정한 것이다.

규칙을 바꾸려면 `terraform/variables.tf`의 두 변수를 바꿔 `make deploy`를 다시 돌린다. interceptor는 guardrail의 작업본(`DRAFT`)이 아니라 고정된 버전을 적용한다. 규칙이 바뀌면 Terraform은 이 순서로 바꾸도록 짜여 있다. guardrail의 작업본을 고치고, 새 버전을 만들고, Lambda의 환경 변수 `GUARDRAIL_VERSION`을 새 버전으로 바꾸고, 그다음에 옛 버전을 지운다(`replace_triggered_by`와 `create_before_destroy`). 그래서 Lambda가 지워진 버전을 가리키는 때가 없다. 옛 버전을 먼저 지우면, 그 사이에 interceptor가 실패하고 에이전트 게이트웨이는 모든 요청을 거부한다. 2026-11-22에 AWS에서 규칙 하나를 바꿔(`code_names`에 지어낸 코드명 하나를 더했다) `make deploy`를 돌렸을 때 Terraform은 이 순서로 바꿨다. guardrail을 그 자리에서 고치고(1초), 새 버전 `2`를 만들고(1초), Lambda의 `GUARDRAIL_VERSION`을 `2`로 바꾸고(6초), 그다음에 옛 버전 `1`을 지웠다(0초). 계획에 든 자원은 이 셋뿐이었다(`1 to add, 2 to change, 1 to destroy`). 그 뒤 Lambda가 가리킨 버전 `2`는 `READY`였고 두 코드명을 모두 담았으며, guardrail에 남은 버전은 작업본과 `2`였다. 그때 interceptor는 게이트웨이에 붙어 있지 않았으므로, 바꾸는 동안 지나가는 호출은 보지 않았다. 같은 날 바뀐 것 없이 `make deploy`를 다시 돌렸을 때는 guardrail을 포함해 아무것도 바뀌지 않았다(`0 added, 0 changed, 0 destroyed`).

## 기본 제공 가드레일과 나눈 일

허브의 가드레일은 두 가지다. 한쪽이 다른 쪽의 결과에 기대지 않도록 검사하는 것을 나눴다.

| | 기본 제공 가드레일 | 커스텀 가드레일 |
|---|---|---|
| 검사하는 것 | 프롬프트 공격(`guard_prompt_<에이전트>`), 비밀값(`guard_secret_<에이전트>`) | 금지어, 사번 |
| 만드는 방법 | 전사 정책(Cedar의 `BedrockGuardrails::...`). 설정이다 | Amazon Bedrock Guardrails의 guardrail과 그것을 부르는 Lambda. 코드다 |
| 하는 일 | 막는다 | 막고, 가린다 |
| 시험 모드 | 기록 모드(`LOG_ONLY`)가 있다 | 없다. 붙어 있는 동안 막고 가린다 |
| 걸리는 곳 | 에이전트마다의 진입(policy engine) | 에이전트 게이트웨이의 모든 target |

기본 제공 가드레일은 [전사 정책](../company_policy/README.md)과 [호스팅 심사](../hosting_review/README.md)에 있다. 가린 요청을 기본 제공 가드레일이 가린 모양으로 보는지, 가리기 전의 모양으로 보는지는 확인하지 않았다.

## Lambda가 실패하면

interceptor Lambda가 오류를 내거나 제한 시간(8초)을 넘기면 에이전트 게이트웨이는 그 요청을 거부한다. 그래서 Lambda가 실패하는 동안에는 모든 에이전트로 들어가는 요청이 막힌다. 이 interceptor의 앞선 판(이 리포에 없는 코드)을 돌린 실행(2026-11-21/22)에서, Lambda가 예외를 내면 0초 만에, 시간을 넘기면 8초 뒤에 게이트웨이가 `400 {"success":false,"error":"The request failed. Set the gateway's exceptionLevel to DEBUG to return the error details."}`를 돌려줬다. 이 리포의 코드로는 확인하지 않았다.

그래서 Terraform이 알람 `<prefix>-guardrail-errors`를 만든다. 네임스페이스 `AWS/Lambda`의 메트릭 `Errors`(차원 `FunctionName=<prefix>-guardrail`)의 1분 합계가 1 이상이면 알림 주제 `<prefix>-alerts`([모니터링](../agent_monitoring/README.md))로 알린다. 알람이 실제로 울리는지는 확인하지 않았다. 게이트웨이가 Lambda를 부르지도 못한 경우(예: 권한)는 Lambda가 실행되지 않았으므로 이 메트릭에 들지 않는다고 본다. 확인하지 않았다.

## 붙이고 떼는 명령

```
platform_team/custom_guardrail/guardrail.sh attach   # 에이전트 게이트웨이에 붙인다
platform_team/custom_guardrail/guardrail.sh status   # 붙었는지, policy engine과 그 모드, target
platform_team/custom_guardrail/guardrail.sh detach   # 뗀다
```

어느 폴더에서 불러도 된다. 허브의 접두어와 리전은 `make`와 같은 규칙으로 리포의 `.env`에서 읽는다([README의 `.env`](../../README.md#env)). 첫 줄에 어느 허브인지(접두어, 리전) 찍는다. 플랫폼팀의 자격 증명으로 돈다.

- `attach`: `UpdateGateway`는 게이트웨이의 설정 전체를 바꾼다. 주지 않은 선택 필드는 초기화된다(서비스 모델의 `UpdateGateway` 설명, botocore 1.44.9). 여기서 이것을 본 것은 interceptor 필드 하나다(아래 "확인한 것과 하지 않은 것"의 `detach`). 다른 필드가 초기화되는 것은 확인하지 않았다. 그래서 먼저 `GetGateway`로 게이트웨이를 읽고, `UpdateGateway`가 받는 설정(이름, 설명, 역할, 인증 방식과 그 설정, protocol과 그 설정, KMS 키, custom transform, policy engine, exception level, WAF, domain)을 읽은 그대로 다시 넘기며 interceptor만 더한다. 다른 interceptor가 있으면 그것도 그대로 둔다. interceptor는 요청(`REQUEST`)과 답(`RESPONSE`) 두 지점에 걸고, 요청의 헤더는 넘기지 않는다(`passRequestHeaders: false`). 그다음 게이트웨이가 `READY`가 되고 바뀐 것이 보일 때까지 300초까지 기다리고, policy engine의 설정과 target의 이름들이 앞과 같은지 본다. 다르면 오류로 끝난다(되돌리지는 않는다). target의 이름은 고치기 직전과 기다린 뒤에 읽으므로, 그 몇 초 사이에 심사의 Entry가 target을 더하거나 반려가 target을 지우면, 고치기가 아무것도 빼지 않았어도 `the agent gateway <이름> changed in the update`로 실패한다(`detach`도 같다). 그때 고치기는 이미 된 것이다. `status`로 target을 보고, 같은 명령을 다시 돌려도 된다. 이미 붙어 있으면(`detach`면 이미 떼어져 있으면) 아무것도 바꾸지 않는다. 코드가 그렇게 하고, 이 겹침은 해 보지 않았다.
- `detach`: 같은 방법으로 이 interceptor만 뺀다. 붙어 있지 않거나, 허브가 올라와 있지 않거나, 게이트웨이가 없으면 아무것도 하지 않고 성공한다.
- `status`: 게이트웨이의 상태, interceptor가 붙었는지와 그 지점, policy engine과 그 모드, target의 이름들을 찍는다.

붙이는 Lambda는 Terraform이 SSM `/<prefix>/platform/interceptor_arn`에 적은 `<prefix>-guardrail`이다. 에이전트 게이트웨이의 역할(`<prefix>-agents-role`)이 부를 수 있는 Lambda는 이 함수 하나다(`lambda:InvokeFunction`, 버전이나 alias가 붙지 않은 ARN). 그래서 `attach`는 이 계정과 리전의 그 함수가 아닌 ARN은 붙이지 않는다. 다른 ARN을 붙이면 게이트웨이가 그 Lambda를 부르지 못해 모든 요청이 막히기 때문이다. 이름이 `<prefix>-agents`가 아닌 게이트웨이도 바꾸지 않는다.

`make destroy`는 다른 무엇보다 먼저 interceptor를 뗀다(`python -m platform_team.custom_guardrail.guardrail_attach detach`). 그래서 게이트웨이가 지워진 Lambda를 가리키는 일이 없다.

## 고객의 가드레일로 바꾸려면

`interceptor_lambda.py`의 `guard(text, source)`를 바꾼다. `text`는 검사할 글, `source`는 `"INPUT"`(요청)이나 `"OUTPUT"`(답)이고, `(막혔는가, 가린 뒤의 글)`을 돌려준다. 본문을 읽고, 403으로 막고, 가린 본문을 넘기는 나머지 코드는 그대로 쓴다. 회사의 Amazon Bedrock Guardrails guardrail을 그대로 쓰려면 Lambda의 환경 변수 `GUARDRAIL_ID`와 `GUARDRAIL_VERSION`, 그리고 역할 `<prefix>-guardrail-role`의 `bedrock:ApplyGuardrail` 자원을 그 guardrail로 바꾼다.

## 확인한 것과 하지 않은 것

2026-11-22에 이 리포의 코드로 확인한 것이다(`us-west-2`, 접두어 `hub`). 에이전트 없이 허브의 틀만 올렸다(`AUTO_APPROVE=1 make deploy`, 228초).

- `guardrail.sh attach`가 이미 있는 에이전트 게이트웨이에 interceptor를 붙였다(5초). 그 뒤의 `status`는 `attached: True (REQUEST, RESPONSE)`였고, policy engine은 그대로 `ENFORCE`였고, target은 붙이기 전처럼 없었다. `attach`를 한 번 더 부르면 `nothing changed`였다.
- Lambda를 직접 두 번 불렀다(`aws lambda invoke`, 게이트웨이가 보내는 모양의 REQUEST 이벤트). 본문이 `{"prompt": "Summarise the schedule of Project Falcon for part P-100."}`이면 `transformedGatewayResponse`에 `statusCode` 403과 `{"error": "Blocked by the company guardrail (interceptor)."}`가 왔다. `{"prompt": "My employee id is EMP-123456."}`이면 `transformedGatewayRequest`의 prompt가 `My employee id is {employee_id}.`였다. Lambda의 역할로 guardrail의 버전 `1`에 `ApplyGuardrail`을 부를 수 있었다는 뜻이기도 하다(역할의 자원은 버전이 붙지 않은 guardrail의 ARN 하나다).
- `guardrail.sh detach`가 interceptor를 뗐다(5초). 그 뒤의 `status`는 `attached: False`였고 policy engine은 그대로 `ENFORCE`였다. interceptor 필드를 빼고 보낸 `UpdateGateway`가 interceptor를 없앤 것이다.
- `AUTO_APPROVE=1 make destroy`는 가장 먼저 interceptor를 떼는 단계를 돌렸고(이미 뗀 뒤라 `attached: False (nothing changed)`), 마지막 줄이 `still present: nothing`이었다(128초). Amazon Bedrock Guardrails의 guardrail(`Bedrock guardrails: none`)과 Lambda `hub-guardrail`, 알람, 역할이 남지 않은 것을 목록으로도 확인했다.

이 interceptor의 앞선 판(이 리포에 없는 코드)을 돌린 실행(2026-11-21/22)에서는 에이전트를 둔 게이트웨이를 지나는 호출로 이렇게 봤다. 금지어가 든 요청은 위의 403으로 막혔다. 도구의 답에 든 사번은 에이전트의 답에서 `{employee_id}`로 가려졌다. 요청의 사번은 가려진 모양으로 에이전트에 닿았다. interceptor를 붙인 뒤에도 policy engine이 남았다. 요청 지점의 interceptor는 정책 결정보다 먼저 돌았다.

2026-11-22의 운영 확인(`make e2e-ops`, 같은 리전과 접두어)에서는 에이전트 둘(`release_review`, `quality_agent`)을 둔 게이트웨이에 이 리포의 명령으로 붙이고 뗐다.

- 붙이기 전에는 `Summarise the schedule of Project Falcon for part P-100.`가 `quality_agent`에서 200이었고, `What was the result of inspection Q-1001, and what is the specification of the part it inspected?`의 답에 도구가 준 사번 `EMP-204817`이 그대로 있었다.
- `guardrail.sh attach`가 5초에 붙였다(`attached: True (changed)`). 앞뒤로 policy engine은 같은 engine의 `ENFORCE`였고 target은 둘이었다. 그 뒤 첫 호출부터(2초) 코드명이 든 요청이 두 에이전트에서 403 `{"error": "Blocked by the company guardrail (interceptor)."}`이었고, 사번 질문의 답에는 `EMP-` 대신 `{employee_id}`가 있었다(`- **Inspector ID:** {employee_id}`).
- 그동안 Lambda의 로그에는 요청 지점의 줄 셋(막음 둘, 그대로 하나)과 답 지점의 줄 셋(가림 하나, 그대로 둘)이 있었다. 게이트웨이가 자기 역할(`<prefix>-agents-role`)로 Lambda를 불렀고, 답 지점이 실제 에이전트의 답을 가린 것이다.
- 붙어 있는 동안 `make preload`가 `docs_adk`를 올렸다(Entry가 target을 더했다). 그 심사의 시험 호출은 기대대로였다(보통 질문 200, 비밀값이 든 질문 403).
- `guardrail.sh detach`가 5초에 뗐고(`attached: False (changed)`), 그 뒤 첫 호출부터(5초) 코드명이 든 요청이 `quality_agent`에서 다시 200이었다.
- 알람 `<prefix>-guardrail-errors`는 허브를 올린 때부터 `OK`였다(알람의 상태 기록).

확인하지 않은 것:

- 스트리밍 응답. interceptor는 답을 한 번에 받는 방식으로만 돌려 봤고, `attach`는 응답을 받는 방식(`responseInterceptionMode`)을 정하지 않는다.
- 금지어의 대소문자와 다른 표기, 한국어 글.
- 가린 요청을 기본 제공 가드레일이 어떤 모양으로 보는지.
- Lambda가 실패할 때의 거부(앞선 실행에서만 봤다)와 알람이 울리는 것.
- interceptor가 붙어 있는 동안 규칙을 바꾸는 것. 규칙을 바꿔 다시 올리는 것은 붙이지 않은 채로만 해 봤다(위의 "무엇을 막고 무엇을 가리나").

## 요금

interceptor가 붙어 있으면 에이전트 게이트웨이를 지나는 호출마다 Lambda가 두 번(요청과 답) 돌고, guardrail이 두 번 검사한다. Amazon Bedrock 요금 페이지(2026-11-22에 읽었다)는 Guardrails를 필터마다 검사한 글의 양(text unit, 1,000자까지가 하나)으로 매기고, 이 guardrail이 쓰는 두 필터(낱말 필터, 정규식의 민감 정보 필터)는 무료라고 적는다. 알람은 CloudWatch 요금 페이지(같은 날 읽었다)에 따르면 그 메트릭마다 시간 단위로 매기고 무료 사용량이 있다. 여기서는 요금을 확인하지 않았다.

## 파일

| 파일 | 역할 |
|---|---|
| `terraform/` | guardrail `<prefix>-company-guardrail`과 그 버전, Lambda `<prefix>-guardrail`, 그 역할 `<prefix>-guardrail-role`(이 guardrail 하나에 `bedrock:ApplyGuardrail`, 자기 로그 그룹에 쓰기), 로그 그룹(14일), 알람 `<prefix>-guardrail-errors`. 내보내는 값은 `interceptor_arn`, `guardrail_id`, `guardrail_version`. 코드는 허브의 코드 묶음 `build/platform_team.zip`이고, 그 안에 `bedrock-runtime`의 API 모델이 들어 있다. |
| `interceptor_lambda.py` | Lambda 진입점(`handler`). 요청과 답을 읽어 `guard`에 넘기고, 막거나 가린 결과를 게이트웨이에 돌려준다. |
| `guardrail_attach.py` | 붙이기(`attach`), 떼기(`detach`), 상태 읽기(`status`), 붙었는지(`attached`), 그리고 명령. |
| `guardrail.sh` | 위의 명령 셋. 리포의 `.env`를 `make`와 같은 규칙으로 읽고 `guardrail_attach`를 부른다. |
