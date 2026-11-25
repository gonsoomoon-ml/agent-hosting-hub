# 에이전트 게이트웨이

사용자가 호스팅된 에이전트를 부르는 문(`<prefix>-agents`)입니다. 모든 요청에 전사 정책을 적용합니다. protocol type이 없는 게이트웨이라서 Runtime target(HTTP)을 받습니다. 에이전트마다 target이 하나 붙고, 그 target은 호스팅 심사가 API로 붙입니다. 커스텀 가드레일(interceptor)도 운영 중에 API로 붙입니다(`guardrail.sh attach`, [커스텀 가드레일](../custom_guardrail/README.md)). 그래서 Terraform은 그 설정을 건드리지 않습니다(`ignore_changes`).

## 개념도에서의 위치

[개념도](../../docs/hosting-hub-concept.png)의 "에이전트 게이트웨이: 요청에 전사 정책 적용" 상자입니다. 흐름 2에서 7a "작업 요청"으로 사용자의 요청을 받고, 7b "요청 전달"로 정책을 통과한 요청만 에이전트 실행 환경에 넘깁니다.

## 파일

| 파일 | 역할 |
|---|---|
| `terraform/` | 게이트웨이와 그 역할 `<prefix>-agents-role`. 역할은 Runtime과 interceptor Lambda를 부르고, policy engine과 `bedrock:InvokeGuardrailChecks`를 씁니다. 내보내는 값은 `gateway_id`, `gateway_arn`, `gateway_url`, `role_arn`. |
| `gateway_targets.py` | 에이전트의 Runtime을 target으로 붙이고(`ensure_runtime_target`), 게이트웨이를 이름으로 찾고(`find_gateway`), target 목록을 읽습니다(`targets`). 같은 이름의 target이 다른 Runtime을 가리키면 바꾸지 않고 오류를 냅니다. |
| `ask_agent.py` | 사용자의 호출을 에이전트 게이트웨이로 보내고 `HTTP <상태> (<초> s)`와 답을 출력합니다(`demo_scenes/ask`). 호출 주소는 `https://<게이트웨이 ID>.gateway.bedrock-agentcore.<리전>.amazonaws.com/<target>/invocations`입니다. 403의 거절 문장(`error` 또는 `message`)도 그대로 출력하고, 계정 ID는 `<ACCOUNT>`로 가립니다. 2026-11-23에 [시연 영상](../../demo_video/README.md)을 녹화하며 사용자의 셸로 돌렸습니다. |
