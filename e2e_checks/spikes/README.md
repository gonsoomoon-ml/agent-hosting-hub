# 확인 테스트

제품의 일부가 아닙니다. 허브를 만들면서 가정을 확인한 실험의 기록입니다(스크립트 둘과 Terraform 폴더 하나). 이 저장소의 어느 명령도 이 폴더의 것을 돌리지 않습니다. `make`의 대상, `publish.sh`, `reject.sh`, `e2e_checks/`의 확인 스크립트, 단위 테스트가 모두 그렇습니다. 아래 표는 실험마다 무엇을 봤는지와 언제 돌렸는지입니다.

| 스크립트 | 무엇을 봤나 | 언제 돌렸나 |
|---|---|---|
| `spike_cli_in_codebuild.py` | AgentCore CLI 1.0.3의 `agentcore deploy`가 CodeBuild 안에서, CDK bootstrap 역할을 맡는 것과 자기 로그를 쓰는 것만 할 수 있는 배포 역할로 Runtime을 올리는가. 첫 build가 네 기준(build 성공, 스택에 Runtime만 있고 IAM 역할은 생기지 않음, `InvokeAgentRuntime` 200, 10분 안)을 모두 지났습니다(316초). 지금의 배포 단계는 CLI를 쓰지 않으므로 이 스크립트는 그 전의 길을 적어 둔 것이고 다시 돌릴 필요가 없습니다. | 2026-11-22 |
| `spike_terraform/` | Terraform(hashicorp/aws 6.73.0)이 허브의 기반 자원의 핵심, 곧 policy engine 하나와 거기에 붙은 게이트웨이 둘(protocol type이 없는 것과 MCP), Lambda 도구 target, Cedar 정책, 카탈로그(registry)를 올리는가. `apply`, 다시 한 `apply`(바뀐 것 없음), `destroy`가 모두 됐습니다. | 2026-11-22 |
| `spike_operations.py` | 운영(에이전트 멈추기, 새 버전의 심사, 도는 에이전트의 경보)이 기대는 가정 일곱. 아래 "운영의 가정"에 본 값과 결정이 있습니다. | 2026-11-22, 두 번 |

## 운영의 가정 (`spike_operations.py`)

`make deploy seed e2e`가 끝난 허브(두 에이전트가 승인된 상태, 도는 심사가 없는 상태)에서 돌립니다. 15분 남짓 걸립니다.

```
AUTO_APPROVE=1 make deploy seed e2e
uv run python e2e_checks/spikes/spike_operations.py 2>&1 | tee e2e_checks/spikes/spike_operations.last-run.log
```

스크립트는 `dev_team/quality_agent`를 임시 폴더에 복사하고 그 `agent.py` 끝에 덮개를 붙여 개발팀 역할로 제출합니다. `agent.json`이 같으므로 이 제출은 승인된 에이전트의 새 버전입니다. 덮개는 두 질문을 따로 받습니다. `spike wait <초>`는 5초마다 `spike tick <n>`을 출력하고 도구(`Quality___get_inspection_data`)를 한 번 부릅니다. `spike loop <초>`는 `spike loop <n>`을 출력하고 실제 에이전트에게 같은 질문을 쉬지 않고 다시 묻습니다(사건의 재시도를 흉내 낸 것입니다). 그 밖의 질문은 원래 에이전트가 받습니다. 리포의 파일은 바꾸지 않습니다. 본 것은 한 줄에 하나씩 `[OBSERVED] <key>: <value>`로 출력하고, 끝 줄은 `== decisions: {...}`(JSON 한 줄)입니다. 계정 ID는 `<ACCOUNT>`로 가립니다. 기록(`spike_operations.last-run.log`)은 커밋하지 않습니다.

스크립트가 만드는 것은 접두어로 시작합니다. 세션 ID는 `hub-spike-<32자>`, 정책은 `stop_agent_quality_agent`입니다. 정책은 `finally`에서 지우고, 마지막 줄 앞에 남은 정책이 없는지 출력합니다(`== stop policy left: none`). 새 버전의 Runtime 버전, 코드 패키지, 심사 실행은 남고 `make destroy`가 지웁니다.

2026-11-22에 두 번 돌렸습니다. 첫 번째 실행은 결정 일곱을 모두 냈지만, 끝에서 스크립트가 정상 종료를 오류로 출력하고(`ERROR SystemExit: 0`) 1로 끝났습니다. 그 결함과 출력의 네 군데(Read의 오류를 실패한 task에서 읽기, 심사가 끝난 뒤의 관찰을 "심사 중"에서 빼기, `STOP_EFFECT`의 값을 마지막 tick과 다음 tick이 올 때로 나누기, 배포 build의 기록에서 pip의 경고 줄 빼기)를 고치고 두 번째로 돌렸습니다. 무엇을 하고 무엇을 보는지는 바꾸지 않았습니다. 아래의 값은 두 실행의 것입니다. 시간은 UTC다.

### 결정

`SEED_EVENT`: `FAILED at Read` (2026-11-22). `make seed`가 공유 도구 레코드(`parts-tools`, 종류 MCP)를 승인 요청 상태로 바꾸자 rule이 심사를 시작했습니다. 그 심사는 Read에서 `ValueError: record type is MCP, not AGENT; …`로 2초 만에 실패했고, 알림 단계(`Notify`)를 지나 끝났습니다. 심사 실행 가운데 이 레코드의 것은 하나였습니다(12:59, `make seed`가 레코드를 처음 만든 때). 그 뒤의 `make seed`는 승인된 레코드를 그대로 두었고 심사가 생기지 않았습니다. 두 실행은 같은 심사 실행 하나를 읽었습니다. 알림의 내용은 보지 않았습니다.

`NEW_VERSION` (2026-11-22, 두 번): 심사 중에도 `GetRegistryRecord`는 새 신청서를 돌려줍니다. 승인된 `quality_agent`를 다시 제출하자 레코드는 바로 `PENDING_APPROVAL`이 되었습니다. 심사 중 30초마다 본 열 번 모두(두 실행 다) 레코드는 `PENDING_APPROVAL`이었고, `GetRegistryRecord`가 돌려준 신청서의 `code_version`은 새 것이었고, 개발팀 역할의 카탈로그 검색(`inspection results and part specifications`)은 `quality_agent`를 찾았습니다. `GetRegistryRecord`의 응답 필드는 `createdAt`, `createdBy`, `description`, `descriptors`, `name`, `recordArn`, `recordId`, `recordType`, `recordVersion`, `registryArn`, `status`, `updatedAt`이고, 승인된 뒤에는 `statusReason`이 더해졌습니다. 심사는 두 번 다 `SUCCEEDED`였습니다. 308초(Read 2초, Scan 26초, Grant 3초, Deploy 266초, Entry 3초, TestCall 7초, Approve 2초)와 296초(2, 34, 3, 244, 3, 8, 2초)입니다. 끝나자 레코드는 `APPROVED`였고 검색이 곧바로 찾았습니다. Runtime의 버전은 1에서 2로, 2에서 3으로 바뀌었습니다. 배포 build는 Runtime을 고쳤고(`UpdateAgentRuntime`, `"created": false`) 새 버전이 241초와 221초 뒤에 `READY`가 되었습니다. 버전을 주지 않은 `GetAgentRuntime`은 고치기 전에는 옛 버전을 `READY`로, 고친 뒤의 첫 관찰(30초 간격)부터는 새 버전을 `UPDATING`으로 보였습니다. DEFAULT endpoint의 `liveVersion`은 새 버전이 되었고, 심사가 끝난 직후의 첫 호출이 게이트웨이를 지나 새 코드에 닿았습니다.

`LONG_CALL` (2026-11-22, 두 번): 에이전트 게이트웨이로 180초 걸리는 요청(`spike wait 180`)을 아무도 멈추지 않으면, 호출자는 182초와 183초 뒤에 200과 끝난 답(`waited, 35 ticks`)을 받았습니다. 게이트웨이는 그사이에 끊지 않았습니다. 호출자가 먼저 포기하면(클라이언트 제한 20초, `spike loop 90`) 에이전트의 반복은 그 뒤에도 70초와 71초 동안 제 끝(90초)까지 돌았습니다. 두 번 다 호출자가 연결을 끊은 뒤에도 반복은 멎지 않았습니다. 60초에 `StopRuntimeSession`으로 멈춘 요청의 호출자는 두 번 다 82초에 500(`{"message":"An unexpected error occurred while processing the request."}`)을 받았습니다.

`SESSION_SOURCE`: `stream-name` (2026-11-22, 두 번). 호출자가 헤더 `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id`에 넣은 세션 ID(`hub-spike-<32자>`, 42자)는 Runtime의 로그 그룹(`/aws/bedrock-agentcore/runtimes/<Runtime ID>-DEFAULT`)에서 log stream의 이름(`runtime-logs-<세션 ID>`)에 있었습니다. 요청이 도는 동안(30초에) 그 stream이 이미 있었습니다. 로그 줄에서는 요청이 끝난 뒤의 한 줄(`bedrock_agentcore.app`의 `Invocation completed successfully`, 필드 `sessionId`)에만 있었고, 도는 동안에는 없었습니다. 헤더 없이 부르면 세션 ID는 UUID(36자)였고, stream `runtime-logs-<UUID>`가 생겼고, 끝 줄의 `sessionId`도 같은 UUID였습니다. 그룹에는 그 밖에 stream `spans`가 있었습니다.

`STOP_EFFECT`: `ends` (2026-11-22, 두 번). `spike wait 180`이 돈 지 60초에 `StopRuntimeSession`(qualifier `DEFAULT`)을 부르자 `statusCode` 200이 돌아왔습니다. 그 뒤 tick 줄은 두 번 더 나왔고(마지막은 멈춘 뒤 10.1초와 10.2초), 그다음 tick(15.4초와 15.5초에 올 차례)부터는 나오지 않았습니다. 도구 Lambda도 함께 멎었습니다(멈춘 뒤 60초 동안 2번과 3번. 3번 가운데 하나는 멈추기 0.1초 전에 출력된 tick의 호출입니다). 반복은 멈춘 뒤 10초에서 16초 사이에 멎었습니다.

`LOOP_RATE`: 47과 39 (2026-11-22, 두 실행이 다릅니다). 쉬지 않는 재시도(`spike loop 90`, 실제 에이전트에게 `What is the result of inspection Q-1002?`를 다시 묻습니다)는 루프 안에 온전히 든 1분 동안 47바퀴와 39바퀴를 돌았습니다. 같은 1분 동안 도구 Lambda도 47번과 39번 불렸고, 도구 게이트웨이의 `Invocations` 메트릭(`Name=Quality___get_inspection_data`, 1분 합)도 47과 39였습니다. 한 바퀴에 도구 호출이 한 번입니다. 90초 전체로는 68바퀴와 51바퀴였습니다. 두 실행의 차이는 모델의 응답 시간에서 오는 것으로 보이지만 확인하지 않았습니다. 메트릭의 차원은 `Method`, `Name`, `Operation`, `Protocol`, `Resource`였습니다.

`STOP_EXCEPTION`: `unless` (2026-11-22, 두 번). 정책 `stop_agent_quality_agent`(`cedar`, `IGNORE_ALL_FINDINGS`, `ACTIVE`)를 아래 문장으로 만들었습니다.

```text
forbid (principal, action == AgentCore::Action::"QualityAgent___POST:/invocations", resource == AgentCore::Gateway::"<에이전트 게이트웨이 ARN>") unless { principal == AgentCore::IamEntity::"arn:aws:sts::<ACCOUNT>:assumed-role/hub-review-testcall-role" };
```

정책은 13초 만에 `ACTIVE`가 되었고, 사용자의 첫 호출부터 403(`Policy evaluation denied due to stop_agent_quality_agent-<접미사>`)이었습니다. 그 상태에서 시험 호출 Lambda `hub-review-testcall`을 직접 부르자 5초 만에 오류 없이 돌아왔습니다(보통 질문 200, 예시 access key가 든 질문 403). 그 직후 사용자의 호출은 여전히 403이었습니다. `unless`가 되었으므로 `when { principal != … }` 모양은 해 보지 않았습니다. 정책을 지우자 정책이 사라지기까지 9초와 5초가 걸렸고, 그 뒤의 첫 사용자 호출이 200이었습니다(지우기를 부른 때부터 16초와 12초).

### 그 밖에 본 것

- 배포 build: CodeBuild 이미지의 Python은 3.13.18이었고, `uv 0.10.8`은 설치 명령(`uv pip install --quiet --no-compile --only-binary :all: --python-platform aarch64-manylinux2014 --python-version 3.13 --target … -r …`)을 그대로 받았습니다(성공한 build 여섯 번). Runtime을 처음 만들 때 `READY`까지 231~232초(세 번), 고칠 때 221~241초(세 번)였습니다. 코드 패키지는 `release_review` 31,584,418바이트, `quality_agent` 30,815,269바이트(덮개를 붙인 것은 30,815,572바이트)였습니다.
- Runtime의 로그 그룹은 `/aws/bedrock-agentcore/runtimes/<Runtime ID>-DEFAULT` 하나였습니다(예: `hub_quality_agent-<10자>-DEFAULT`). `GetAgentRuntime`이 돌려준 `lifecycleConfiguration`은 `idleRuntimeSessionTimeout` 900, `maxLifetime` 28800이었습니다. 허브는 이 값을 정하지 않습니다.
- Runtime의 workload identity는 Runtime ID와 같은 이름이었습니다(`hub_quality_agent-<10자>`).
- 지우기: `DeleteAgentRuntime` 뒤에 `GetAgentRuntime`이 처음 보인 상태는 `DELETING`이었습니다(1초 간격으로 읽었습니다). 약 195초 뒤 `ResourceNotFoundException`이 되었고, 그때 workload identity도 목록에서 사라졌습니다. `reject.sh` 한 번과 `make destroy`의 Runtime 둘에서 같았습니다. 이 관찰은 이 스크립트가 아니라 `make destroy` 옆에서 돌린 읽기 전용 확인으로 했습니다.
