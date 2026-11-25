# 확인 테스트

제품의 일부가 아닙니다. 허브를 만들면서 가정을 확인한 실험 셋의 기록입니다. 이 저장소의 어느 명령도 이 폴더의 것을 돌리지 않습니다.

| 실험 | 물은 것 | 답과 그 뒤 |
|---|---|---|
| `spike_cli_in_codebuild.py` (2026-11-22) | AgentCore CLI 1.0.3의 `agentcore deploy`가 CodeBuild 안에서, 권한을 좁힌 배포 역할로 Runtime을 올리는가 | 됩니다. 첫 build가 네 기준(build 성공, IAM 역할이 생기지 않음, `InvokeAgentRuntime` 200, 10분 안)을 지났습니다. 지금의 배포 단계는 CLI를 쓰지 않으므로 다시 돌릴 필요가 없습니다. |
| `spike_terraform/` (2026-11-22) | Terraform(hashicorp/aws 6.73.0)이 허브의 핵심 자원(policy engine, 게이트웨이 둘, Lambda 도구 target, Cedar 정책, 카탈로그)을 올리는가 | 됩니다. `apply`, 다시 한 `apply`, `destroy`가 모두 됐습니다. 허브의 기반 자원은 Terraform으로 올립니다. |
| `spike_operations.py` (2026-11-22, 두 번) | 운영(에이전트 멈추기, 새 버전의 심사, 도는 에이전트의 경보)이 기대는 가정 일곱 | 아래 "결정"에 있습니다. |

## 운영의 가정 (`spike_operations.py`)

`make deploy seed e2e`가 끝나 두 에이전트가 승인되고 도는 심사가 없는 허브에서 돌립니다. 15분 남짓 걸립니다.

```
AUTO_APPROVE=1 make deploy seed e2e
uv run python e2e_checks/spikes/spike_operations.py 2>&1 | tee e2e_checks/spikes/spike_operations.last-run.log
```

- `dev_team/quality_agent`의 복사본에 덮개를 붙여 새 버전으로 제출하고, 본 것을 `[OBSERVED] <key>: <value>`로 출력합니다. 리포의 파일은 바꾸지 않습니다.
- 멈춤 정책 `stop_agent_quality_agent`는 끝에 지웁니다. 새 버전의 Runtime 버전, 코드 패키지, 심사 실행은 남고 `make destroy`가 지웁니다.

### 결정

2026-11-22에 두 번 돌린 값입니다.

| 결정 | 본 것 | 허브가 그래서 하는 일 |
|---|---|---|
| `SEED_EVENT`: `FAILED at Read` | 공유 도구 레코드(`parts-tools`, 종류 MCP)의 승인 요청이 심사를 시작했고, 심사는 Read에서 실패했습니다. | 지금의 심사는 AGENT가 아닌 레코드를 건너뛰고 알림 없이 끝납니다. |
| `NEW_VERSION` | 승인된 에이전트를 다시 제출하자 레코드가 바로 `PENDING_APPROVAL`이 되었고, `GetRegistryRecord`는 새 신청서를 돌려줬습니다. 심사가 끝난 직후의 첫 호출은 새 코드에 닿았습니다. | 새 버전의 심사는 방금 제출된 신청서를 읽고, 있는 Runtime을 고칩니다(`UpdateAgentRuntime`). |
| `LONG_CALL` | 게이트웨이는 180초 걸리는 요청을 끊지 않았습니다. 호출자가 20초에 포기해도 에이전트의 반복은 70초와 71초 더 돌았습니다. | 멈춤 명령은 세션을 끝냅니다. 사고 버전에는 시간 상한을 둡니다([quality_agent](../../dev_team/quality_agent/README.md)). |
| `SESSION_SOURCE`: `stream-name` | 세션 ID는 Runtime의 로그 그룹에서 log stream의 이름(`runtime-logs-<세션 ID>`)에 있었고, 요청이 도는 동안 이미 있었습니다. 헤더 없이 부르면 세션 ID는 UUID였고, 그 이름의 stream이 생겼습니다. | 멈춤 명령은 이 stream 이름으로 세션을 찾습니다. |
| `STOP_EFFECT`: `ends` | `StopRuntimeSession`을 부른 뒤 10초에서 16초 사이에 요청과 도구 호출이 멎었고, 호출자는 500을 받았습니다. | 멈춤 명령은 진입을 막은 뒤 세션을 `StopRuntimeSession`으로 끝냅니다. |
| `LOOP_RATE`: 47과 39 | 쉬지 않는 재시도는 1분에 도구를 47번과 39번 불렀고, 도구 게이트웨이의 `Invocations` 메트릭도 같은 수였습니다. 두 실행의 차이가 어디서 오는지는 확인하지 않았습니다. | 도는 에이전트의 경보가 이 메트릭을 보고, 임계값은 낮은 쪽(39)의 절반입니다([모니터링](../../platform_team/agent_monitoring/README.md)). |
| `STOP_EXCEPTION`: `unless` | 아래 정책이 `ACTIVE`가 되자 사용자의 호출은 403이었고, 시험 호출 Lambda `hub-review-testcall`은 그대로 지났습니다. | 멈춤 정책은 이 모양으로 시험 호출의 역할만 빼고 막습니다([에이전트 멈추기](../../platform_team/agent_stop/README.md)). |

```text
forbid (principal, action == AgentCore::Action::"QualityAgent___POST:/invocations", resource == AgentCore::Gateway::"<에이전트 게이트웨이 ARN>") unless { principal == AgentCore::IamEntity::"arn:aws:sts::<ACCOUNT>:assumed-role/hub-review-testcall-role" };
```

그 밖에 Runtime의 `lifecycleConfiguration`은 `idleRuntimeSessionTimeout` 900, `maxLifetime` 28800이었습니다. 허브는 이 값을 정하지 않습니다.
