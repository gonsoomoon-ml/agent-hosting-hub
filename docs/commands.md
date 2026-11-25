# 명령 모음

[README](../README.md)로 돌아가기

허브를 올린 뒤에 쓰는 명령과 허브 화면을 적습니다.

## 운영의 명령

플랫폼팀이 허브를 운영하는 명령입니다. 어느 폴더에서 불러도 되고, `.env`를 `make`와 같은 규칙으로 읽고, 플랫폼팀의 자격 증명으로 돕니다. 첫 줄에 어느 허브인지(접두어, 리전) 출력하고, 실패하면 이유를 한 줄로 출력하고(계정 ID는 `<ACCOUNT>`로 가립니다) 0이 아닌 값으로 끝납니다. 시간은 운영을 확인한 실행(`make e2e-ops`, [확인한 것](checks.md#make-e2e-ops가-확인하는-것))에서 잰 것입니다.

| 명령 | 하는 일 | 걸린 시간 |
|---|---|---|
| `platform_team/company_policy/rollout.sh <정책> log-only\|active\|off\|report` | 전사 정책(지금은 `guard_prompt` 하나)을 호스팅된 에이전트 모두에 기록 모드나 적용 모드로 켜고, 모드를 바꾸고, 끄고, 지난 60분의 기록(`LogOnlyMatches`, `LogOnlyDecisionFlips`)을 보여 줍니다. 모드를 SSM `/<prefix>/policies/`에 적어 두므로 나중에 승인되는 에이전트에도 걸립니다. [전사 정책](../platform_team/company_policy/README.md#전사-정책-켜고-끄기) | 에이전트 둘에 켜기 27초, 둘의 모드 바꾸기 35초, 셋에서 끄기 27초. 두 번째 실행에서 셋에 켜기 44초, 셋의 모드 바꾸기 56초, 셋에서 끄기 27초 |
| `platform_team/custom_guardrail/guardrail.sh attach\|detach\|status` | 커스텀 가드레일(interceptor Lambda)을 에이전트 게이트웨이에 붙이고 뗍니다. 게이트웨이의 다른 설정, policy engine, target은 그대로 둡니다. [커스텀 가드레일](../platform_team/custom_guardrail/README.md#붙이고-떼는-명령) | 붙이기 5초(그 뒤 첫 호출부터 코드명이 막혔습니다), 떼기 5초 |
| `platform_team/agent_stop/stop.sh <에이전트> [--session <ID> ...]` | 에이전트 하나의 진입을 막고(`stop_agent_<에이전트>`), 그 Runtime의 최근 세션을 끝냅니다. 심사의 시험 호출은 막지 않습니다. 이웃 에이전트는 건드리지 않습니다. [에이전트 멈추기와 재개](../platform_team/agent_stop/README.md) | 20초(정책이 `ACTIVE`가 되기까지와 세션 여덟). 두 번째 실행에서 17초(세션 열둘) |
| `platform_team/agent_stop/resume.sh <에이전트>` | 멈춤 정책을 지웁니다. 그 밖의 것은 바꾸지 않습니다. | 8초와 12초(그 뒤 첫 호출부터 200) |
| `platform_team/agent_monitoring/usage.sh [분]` | 에이전트마다 불린 수, 세션, 오류, CPU와 메모리, 도구마다 불린 수를 CloudWatch 메트릭에서 읽어 표로 출력합니다. 읽기만 합니다. [모니터링](../platform_team/agent_monitoring/README.md#사용량-보고) | 2초 |

## 허브 화면(샘플)

`make ui`는 플랫폼팀의 샘플 화면을 이 PC에서 실행합니다(`http://127.0.0.1:8300`). 브라우저에서 허브의 지금 상태(플랫폼 구성과 그것을 돌리는 AWS 서비스, 호스팅된 에이전트와 승인 대기 중인 에이전트의 수, 전사 정책의 모드, 커스텀 가드레일, 경보, 카탈로그)와 에이전트 신청마다 가장 최근 호스팅 심사의 일곱 단계, 두 게이트웨이의 정책, 에이전트의 사용량과 도구 호출 경보를 그 순간 AWS에서 읽어 보입니다. 로그인이 없고 `127.0.0.1`에서만 듣습니다. 실행한 셸의 자격 증명으로 돕니다. 다른 사이트의 페이지가 브라우저를 통해 이 화면을 쓰지 못하게 하는 규칙과 그 규칙이 막지 못하는 것, 값을 읽는 곳은 [허브 화면](../platform_team/hub_ui/README.md)에 있습니다. 페이지는 넷입니다(홈, 호스팅 심사, 전사 정책, 에이전트). 버튼은 셸 명령과 같은 함수를 부릅니다(반려는 `reject.sh`, 전사 정책의 모드는 `rollout.sh`, 커스텀 가드레일은 `guardrail.sh`, 멈춤과 재개는 `stop.sh`와 `resume.sh`). `make e2e-ui`는 `make e2e-ops`가 끝난 허브에서 화면을 이 PC의 빈 포트에서 실행하고, 페이지를 읽고 버튼을 눌러 확인 여덟을 출력합니다([허브 화면의 테스트와 확인](../platform_team/hub_ui/README.md#테스트와-확인), 기록은 `e2e_checks/last-run-ui.log`). 2026-11-23에 같은 허브에서 두 번 돌려 두 번 모두 8개 통과했습니다(774초와 851초. 네 페이지를 20초씩 둔 시간이 들어 있습니다).

## 영상에서 치는 명령

시연 영상의 터미널 장면에서 사람이 치는 짧은 명령 넷이 `demo_scenes/`에 있습니다. `ask`(에이전트 부르기), `publish`(에이전트 올리기), `search`(카탈로그 검색), `logs`(에이전트의 최근 로그). 각 명령, 프롬프트, 장면의 순서는 [`demo_scenes/README.md`](../demo_scenes/README.md)에 있습니다. `search`와 `logs`는 2026-11-23에 개발자 PC(아래)에서 개발팀 역할로 돌렸고, 같은 날 시연 영상의 녹화에서 `publish`는 개발자 PC에서, `ask`는 사용자의 셸에서 돌렸습니다.

개발자 장면을 녹화하는 PC는 Docker 컨테이너이고 [`demo_video/README.md`](../demo_video/README.md)에 있습니다. Claude Code가 Amazon Bedrock의 모델로 돌고, 컨테이너에는 개발팀 역할의 임시 자격 증명과 두 Claude 모델만 부를 수 있는 임시 토큰만 들어갑니다. 2026-11-23에 그 안의 Claude Code가 카탈로그의 MCP endpoint로 `parts-tools`를 찾았고, 템플릿으로 에이전트의 파일을 만들었습니다.
