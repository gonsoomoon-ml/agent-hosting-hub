# 에이전트 게이트웨이

사용자가 호스팅된 에이전트를 부르는 문(`<prefix>-agents`)입니다. 모든 요청에 전사 정책을 적용합니다. protocol type이 없는 게이트웨이라서 Runtime target(HTTP)을 받습니다. 에이전트마다 target이 하나 붙고, 그 target은 호스팅 심사가 API로 붙입니다. 커스텀 가드레일(interceptor)도 운영 중에 API로 붙입니다(`guardrail.sh attach`, [커스텀 가드레일](../custom_guardrail/README.md)). 그래서 Terraform은 그 설정을 건드리지 않습니다(`ignore_changes`).

## 개념도에서의 위치

[개념도](../../docs/hosting-hub-concept.png)의 "에이전트 게이트웨이: 요청에 전사 정책 적용" 상자입니다. 흐름 2에서 7a "작업 요청"으로 사용자의 요청을 받고, 7b "요청 전달"로 정책을 통과한 요청만 에이전트 실행 환경에 넘깁니다.

## 두 게이트웨이

허브의 문은 둘입니다. 이 게이트웨이는 사용자와 에이전트 사이에, [도구 게이트웨이](../tool_gateway/README.md)는 에이전트와 사내 도구 사이에 있습니다. 둘 다 같은 policy engine `<prefix>_pe`를 `ENFORCE`로 따르고, 호출자를 IAM(SigV4 서명)으로 확인합니다.

```
사용자 (demo_scenes/ask)
  │  POST https://<게이트웨이 ID>.gateway.bedrock-agentcore.<리전>.amazonaws.com/<target>/invocations
  ▼
┌─ 에이전트 게이트웨이 <prefix>-agents ───────────────
│   판정: entry_permit, review_permit, guard_secret, guard_prompt, stop_agent
│   interceptor: 커스텀 가드레일 (붙어 있을 때)
│   target: QualityAgent, ReleaseReview, DocsAdk …   (에이전트마다 하나, 심사의 Entry가 붙입니다)
└──────────────────────────────────────────────────
  │  InvokeAgentRuntime (게이트웨이 역할 <prefix>-agents-role)
  ▼
Runtime <prefix>_<에이전트>  ── 팀의 코드
  │  hub_tools.call_tool("Parts___get_part_spec", …)   MCP tools/call, 에이전트 실행 역할로 서명
  ▼
┌─ 도구 게이트웨이 <prefix>-tools  (MCP) ─────────────
│   판정: tool_<에이전트>_<Target>_<도구>  (실행 역할마다, 도구마다 permit)
│   target: Quality, Parts, Release   (Terraform이 만듭니다)
└──────────────────────────────────────────────────
  │  lambda:InvokeFunction (게이트웨이 역할 <prefix>-tools-role)
  ▼
도구 Lambda (sample_tools, target 셋이 같은 Lambda)
```

```
                     에이전트 게이트웨이            도구 게이트웨이
이름                 <prefix>-agents               <prefix>-tools
protocol type        없음 (HTTP)                   MCP
target               Runtime (에이전트마다 하나)     Lambda (Quality, Parts, Release)
target을 붙이는 것    호스팅 심사의 Entry (API)       Terraform
action 이름          <Target>___POST:/invocations  <Target>___<tool>
permit의 principal   누구나 (entry_permit)          그 에이전트의 실행 역할만
interceptor          커스텀 가드레일                 없음
호출하는 쪽           사용자, 심사의 TestCall          에이전트, 개발자 역할
```

정책이 요청을 판정하는 방법은 [전사 정책](../company_policy/README.md#정책이-요청을-판정하는-방법)에 있습니다. 진입 정책은 이 게이트웨이를 지날 때만 걸리고, Runtime을 직접 부르는 호출에는 걸리지 않습니다([한계](../../docs/limits.md)).

## 파일

| 파일 | 역할 |
|---|---|
| `terraform/` | 게이트웨이와 그 역할 `<prefix>-agents-role`. 역할은 Runtime과 interceptor Lambda를 부르고, policy engine과 `bedrock:InvokeGuardrailChecks`를 씁니다. 내보내는 값은 `gateway_id`, `gateway_arn`, `gateway_url`, `role_arn`. |
| `gateway_targets.py` | 에이전트의 Runtime을 target으로 붙이고(`ensure_runtime_target`), 게이트웨이를 이름으로 찾고(`find_gateway`), target 목록을 읽습니다(`targets`). 같은 이름의 target이 다른 Runtime을 가리키면 바꾸지 않고 오류를 냅니다. |
| `ask_agent.py` | 사용자의 호출을 에이전트 게이트웨이로 보내고 `HTTP <상태> (<초> s)`와 답을 출력합니다(`demo_scenes/ask`). 호출 주소는 `https://<게이트웨이 ID>.gateway.bedrock-agentcore.<리전>.amazonaws.com/<target>/invocations`입니다. 403의 거절 문장(`error` 또는 `message`)도 그대로 출력하고, 계정 ID는 `<ACCOUNT>`로 가립니다. 2026-11-23에 [시연 영상](../../demo_video/README.md)을 녹화하며 사용자의 셸로 돌렸습니다. |
