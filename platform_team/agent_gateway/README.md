# 에이전트 게이트웨이

사용자가 호스팅된 에이전트를 부르는 문(`<prefix>-agents`)이다. 모든 요청에 전사 정책을 적용한다. protocol type이 없는 게이트웨이라서 Runtime target(HTTP)을 받는다. 에이전트마다 target이 하나 붙고, 그 target은 호스팅 심사가 API로 붙인다. 커스텀 가드레일(interceptor)도 운영 중에 API로 붙이므로(`guardrail.sh attach`, [커스텀 가드레일](../custom_guardrail/README.md)) Terraform은 그 설정을 건드리지 않는다(`ignore_changes`).

## 개념도에서의 위치

"에이전트 게이트웨이: 요청에 전사 정책 적용" 상자다. ⑦ "작업 요청, 요청 전달"에서 사용자의 요청을 받고, 정책을 통과한 요청만 에이전트 실행 환경에 넘긴다.

## 파일

| 파일 | 역할 |
|---|---|
| `terraform/` | 게이트웨이와 그 역할 `<prefix>-agents-role`(Runtime 호출, interceptor Lambda 호출, policy engine, `bedrock:InvokeGuardrailChecks`). 내보내는 값은 `gateway_id`, `gateway_arn`, `gateway_url`, `role_arn`. |
| `gateway_targets.py` | 에이전트의 Runtime을 target으로 붙이고(`ensure_runtime_target`), 게이트웨이를 이름으로 찾고(`find_gateway`), target 목록을 읽는다(`targets`). 같은 이름의 target이 이미 있으면 그 target이 같은 Runtime을 가리킬 때만 그대로 쓴다. 다른 Runtime을 가리키면 바꾸지 않고 오류를 낸다. |
