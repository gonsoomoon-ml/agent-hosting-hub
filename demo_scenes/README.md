# 데모 장면의 명령

시연 영상의 터미널 장면에서 사람이 치는 명령 넷이다. 각각 짧은 셸 파일이고, 허브의 환경 값(접두어, 리전, 모델)을 `platform_team/shared_code/hub_env.sh`로 읽은 다음 Python 모듈 하나를 부른다. Python은 `-I`(격리 모드)로 띄워서, 명령을 부른 폴더의 파일을 모듈로 불러오지 않고(그 폴더의 `json.py` 같은 파일이 표준 모듈을 가리지 못한다), 부른 쪽의 `PYTHON…` 환경 변수와 사용자 site 폴더도 읽지 않는다. 허브의 모듈은 프로젝트의 편집 가능 설치(`uv sync`)로 찾는다. 파일의 위치에서 저장소의 루트를 찾으므로 어느 폴더에서 쳐도 된다. 첫 줄에 부르는 명령을 한 줄(100칸 이내)로 찍고, 그다음에 결과를 찍는다. 기대한 실패(403, 없는 에이전트, 로그 그룹 없음)는 Python 오류 출력 없이 한 줄로 말한다. 찍는 글에서 계정 ID는 `<ACCOUNT>`로 가린다.

이 명령들은 단위 시험(`tests/test_ask_agent.py`, `test_search_catalog.py`, `test_agent_logs.py`, `test_demo_scenes.py`)으로 확인했다. AWS에서는 2026-11-23에 시연 영상의 개발자 PC(`demo_video/tools/dev_pc`)에서 개발팀 역할로 `search`와 `logs`를 돌렸다(아래). `publish`(개발자 PC)와 `ask`(사용자의 셸)는 같은 날 시연 영상의 녹화에서 돌렸다(`demo_video/README.md`의 장면 표). 아래 "프롬프트" 열은 `make e2e`와 `make e2e-ops`가 2026-11-22와 2026-11-23의 실행에서 쓴 문장이고, 그 가운데 녹화에서 이 명령으로 보낸 것은 장면 표에 있다.

## 명령

| 명령 | 누가 치나 | 하는 일 | 성공하면 | 거절하면 |
|---|---|---|---|---|
| `demo_scenes/ask <에이전트> "<프롬프트>"` 또는 `--file <경로>` (`--timeout <초>`, `--session <ID>`) | 사용자(에이전트 게이트웨이를 부를 수 있는 IAM 주체) | 에이전트 게이트웨이로 에이전트를 부른다 | 첫 줄 `HTTP 200 (<초> s)`, 그다음 줄부터 답. 종료 값 0 | 첫 줄 `HTTP 403 (<초> s)`, 그다음 줄에 게이트웨이의 문장(`error` 또는 `message`). 종료 값 1. 에이전트 이름이 신청서의 규칙에 맞지 않으면 아무것도 부르지 않고 한 줄로 이유를 말하고 종료 값 2. 시간 안에 답이 없으면 한 줄(`no answer from <에이전트> within <초> s`)과 종료 값 1 |
| `demo_scenes/publish <에이전트> [변형]` | 개발자 | `dev_team/<에이전트>`의 코드를 올리고, 신청서를 카탈로그에 쓰고, 승인을 요청한다(호스팅 심사가 시작된다) | `platform_team/agent_catalog/publish_agent.py`가 찍는 줄(올린 곳, record, 상태) | 없는 에이전트나 없는 변형이면 있는 것의 목록을 한 줄로 말하고 종료 값 2. 올리기에 실패하면 `publish_agent.py`의 한 줄 |
| `demo_scenes/search "<검색어>"` | 개발자 | 카탈로그를 검색한다. 승인된 record만 나온다 | record마다 `이름  (종류)`, 설명, 도구라면 `tool <이름>: <입력 필드>` | 맞는 것이 없으면 `no approved record matches "<검색어>"`(종료 값 0). 검색을 못 하면 한 줄과 종료 값 1 |
| `demo_scenes/logs <에이전트> [분]` | 개발자 | 에이전트의 Runtime 로그 그룹에서 가장 새 줄 200개까지를 오래된 줄부터 보인다(분은 15가 기본) | 첫 줄 `<에이전트>: the newest <n> log lines of the last <분> minutes`, 그다음 줄부터 로그 | 로그 그룹이 없으면 `no log group for <에이전트> ...` 한 줄과 종료 값 1. 그 시간에 줄이 없으면 한 줄과 종료 값 0 |

- `publish`의 변형은 `dev_team/<에이전트>/variants/` 아래의 폴더다. 지금 있는 것은 `quality_agent`의 `v1-vulnerable`(취약한 라이브러리)과 `v2-loop`(도구를 되풀이해 부르는 판)이다.
- `logs`는 `runtime-logs-<세션 ID>` 스트림의 줄만 읽는다. `otel-rt-logs`(2026-11-22에 같은 줄의 복사본이 있었다)와 `spans`, `build-logs-*`는 읽지 않는다. 쓰는 호출은 `DescribeLogGroups`와 `FilterLogEvents`뿐이라 SSM을 읽지 않는다. 개발팀 역할(`platform_team/dev_access`)은 허브 Runtime(`<prefix>_<에이전트>`)의 로그 그룹을 읽을 수 있다. 그 역할 하나가 모든 팀에 쓰이므로 개발자는 허브의 모든 에이전트의 로그 줄을 읽는다([개발팀의 권한](../platform_team/dev_access/README.md#mcp-endpoint와-로그-권한)). 거꾸로 보면, 호스팅된 에이전트의 코드가 로그에 쓰는 글은 무엇이든 개발자의 코딩 도우미(예: 시연 영상의 Claude Code)가 `logs`로 읽는 글이다. 그 글은 믿지 않는 글로 다룬다(지시로 받지 않는다). harness 에이전트 `spec_assistant`의 Runtime(`harness_<prefix>_spec_assistant`)의 로그는 그 역할에 주지 않았으므로, 그 에이전트에는 `logs`가 거부를 한 줄로 말하고 종료 값 1로 끝난다. 2026-11-23에 개발팀 역할로 돌렸을 때 `logs docs_adk 60`은 줄 다섯을 찍었고, `logs spec_assistant 60`은 `logs of spec_assistant did not finish: AccessDeniedException: ...`(`logs:FilterLogEvents`가 거부되었다는 한 줄, 계정은 가려졌다)과 종료 값 1, `logs quality_agent`(올라와 있지 않았다)는 `no log group for quality_agent ...`와 종료 값 1이었다.
- `search`와 `ask`는 허브가 SSM `/<접두어>/platform`에 적어 둔 값(카탈로그 ID, 게이트웨이 ID)을 읽는다. `search`가 record의 도구 입력 필드를 보이는 것은 검색 결과나 `GetRegistryRecord`가 record의 custom descriptor를 주는 경우다. 2026-11-23에 개발팀 역할로 돌린 `search "part specification tool"`은 `parts-tools`의 도구 둘과 그 입력 필드(`tool get_part_spec: part_id`, `tool get_test_result: part_id`)를 찍었다.

## 입력 파일

- `demo_scenes/inputs/change-ok.txt`: `release_review`에게 보내는 변경 설명. 규칙을 모두 지킨다(`make e2e`의 같은 문장은 2026-11-23의 실행에서 200과 `OK`를 받았다).
- `demo_scenes/inputs/change-with-hidden-instruction.txt`: 같은 변경 설명 다음에, 빈 줄 하나를 두고 `make e2e-ops`가 `HIDDEN`으로 쓰는 문장(앞선 지시를 무시하라는 문장)을 제 문단으로 덧붙였다. 2026-11-23(UTC)에 기록 모드의 `guard_prompt`로 두 꼴을 보냈다. 처음 꼴은 그 문장을 주석 한 줄(`# Note for the reviewer: ` 다음)에 넣은 것이었다. 13:42에 `release_review`와 `docs_adk`에 보냈고 둘 다 200이었지만, 3분 반 뒤까지 정책의 집계(`LogOnlyMatches`)가 두 에이전트 모두 0이었다. 정책이 그 문장을 잡지 않았다. 지금의 꼴(문장이 제 문단)은 13:46에 같은 두 에이전트에 보냈고 둘 다 200이었고, 56초 뒤의 집계가 두 에이전트 모두 `LogOnlyMatches 1, LogOnlyDecisionFlips 1`이었다.

## 장면의 순서

각 장면의 명령(프롬프트는 명령에 적혀 있다), 장면이 필요로 하는 상태와 남기는 상태다. 허브가 올라와 있고(`make deploy`, `make seed`, `make preload`가 끝나 있다) 개발자 컨테이너나 사용자 셸에 각자의 자격 증명이 있다고 본다.

| 장면 | 명령 | 필요한 상태 | 남기는 상태 |
|---|---|---|---|
| 호스팅 신청 | `demo_scenes/publish quality_agent v1-vulnerable`, `demo_scenes/publish release_review` | 두 에이전트가 아직 없다 | 두 record가 승인 대기이고 호스팅 심사 둘이 돈다 |
| 호스팅된 에이전트를 부른다 | `demo_scenes/ask release_review --file demo_scenes/inputs/change-ok.txt` | `release_review`가 승인되어 호스팅 중이다 | 없다 |
| 취약한 판을 고쳐 다시 신청한다 | `demo_scenes/publish quality_agent` | `quality_agent`의 취약한 판이 반려되어 있다 | 새 판의 심사가 돈다 |
| 승인된 에이전트가 답한다 | `demo_scenes/ask quality_agent "What is the spec of part P-100?"` | `quality_agent`가 승인되어 있다 | 없다 |
| 전사 정책이 숨은 지시를 막는다(기록 모드에서는 지나고, 적용 모드에서는 막는다) | `demo_scenes/ask release_review --file demo_scenes/inputs/change-with-hidden-instruction.txt`(기록 모드일 때와 적용 모드일 때), 같은 파일로 `docs_adk`도 | 전사 정책 `guard_prompt`가 해당 모드이다 | 없다. 기록 모드에서 이 파일을 `release_review`와 `docs_adk`에 보낸 것은 위의 "입력 파일"에 있다(2026-11-23) |
| 커스텀 가드레일 전과 후 | 전: `demo_scenes/ask quality_agent "Summarise the schedule of Project Falcon for part P-100."`, 후: 같은 명령과 `demo_scenes/ask quality_agent "What was the result of inspection Q-1001, and what is the specification of the part it inspected?"` | 후에는 커스텀 가드레일이 붙어 있다 | 없다 |
| 사고(도구를 되풀이해 부르는 판) | `demo_scenes/publish quality_agent v2-loop`, 심사가 끝난 뒤 `demo_scenes/ask quality_agent "What is the result of inspection Q-1002?" --timeout 60` | `quality_agent`의 한 판이 승인되어 있다 | 그 에이전트가 되풀이 호출을 계속한다. 도구 호출 경보가 울린다. `make e2e-ops`의 호출은 20초에 포기한다. 2026-11-23의 시연 영상 녹화(`52-incident`)에서 이 명령의 `--timeout 60`은 61초 뒤에 `no answer from quality_agent within 60 s (TimeoutError)`를 찍었다 |
| 이웃은 영향이 없다 | `demo_scenes/ask quality_agent "What is the spec of part P-100?"`, `demo_scenes/ask release_review --file demo_scenes/inputs/change-ok.txt`, `demo_scenes/ask docs_adk "What is our standard for versioning an API?"` | `quality_agent`를 멈춘 상태다 | 없다. `quality_agent`는 403, 나머지는 200이다 |
| 원인을 로그에서 본다 | `demo_scenes/logs quality_agent` | 사고의 판이 돌았다 | 없다. 되풀이하는 줄은 `asking again (<n>)`이다. 2026-11-23의 `make e2e-ops`(UTC 07:22~07:23)에서는 분당 23줄과 25줄이었다. 같은 날의 녹화(UTC 14:10~14:12, 커스텀 가드레일이 붙어 있었다)에서는 1번째(14:10:22)부터 50번째(14:11:32)까지 약 71초로 한 번에 약 1.4초였다. 경보의 막대(도구 호출, 분당)는 경보 장면(`53-alarm`)의 화면에서 첫 분(그 분의 일부만 든다)이 27이었고, 멈추는 장면(`54-stop`)의 화면에서 그다음 두 분이 43과 45였다 |
| 고친 판으로 돌아온다 | `demo_scenes/publish quality_agent`, 승인된 뒤 `demo_scenes/ask quality_agent "What was the result of inspection Q-1001, and what is the specification of the part it inspected?"` | 에이전트가 멈춰 있고 고친 판을 올린다. 재개한 뒤에 부른다 | 고친 판이 승인되어 돈다 |

카탈로그 검색은 `demo_scenes/search "inspection results and part specifications"`가 `make e2e-ops`의 검색어이고(2026-11-23에 다섯 record를 돌려주었다), `demo_scenes/search "part specification tool"`과 `demo_scenes/search "release rules review request"`가 `make e2e`의 검색어다. 2026-11-23에 개발자 PC에서 개발팀 역할로 이 명령을 돌린 검색어는 `"part specification tool"`(`parts-tools`와 `spec_assistant`가 나왔다)과, Claude Code가 이 명령으로 친 `"부품 규격"`(맞는 record가 없었다), `"part specification"`, `"datasheet"`, `"spec"`, `"부품"`이다. 뒤의 넷은 한 명령으로 돌았고, `"part specification"`이 `spec_assistant`와 `parts-tools`를 찾았고 나머지 셋은 맞는 record가 없었다(그 Claude Code 세션의 기록에서 읽었다).

위 표에서 `P-100`의 규격을 묻는 문장은 `make e2e-ops`가 첫 확인에서 쓰는 보통의 질문(`NORMAL`)이다. 2026-11-23의 녹화(`26-answers`)에서 이 명령으로 그 문장을 `quality_agent`에게 보내 200과 P-100의 규격을 받았다.
