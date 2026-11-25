# 개발팀의 권한

개발팀이 심사를 받기 전부터 할 수 있는 일을 정합니다. 개발팀 역할 `<prefix>-dev-role`을 맡으면 다섯 가지를 할 수 있습니다. 도구 게이트웨이로 공유 읽기 도구(`SHARED_READ`, 지금은 `Parts___get_part_spec`)를 부르고, 카탈로그를 검색하고(Registry의 MCP endpoint로도), 레코드를 만들어 승인을 요청하고, 허브의 값(SSM `/<prefix>/platform/` 아래의 게이트웨이와 카탈로그의 ID, 제출 버킷의 이름)을 읽고, 허브 Runtime의 로그 줄을 읽습니다(쓰지는 못합니다). 허브의 값을 읽는 것은 `publish.sh`가 이 역할로 돌면서 제출 버킷과 카탈로그를 여기서 찾기 때문입니다. 이 권한은 실행해서 찾았습니다(`ssm:GetParametersByPath`가 없어 제출이 거부됐습니다). MCP endpoint는 개발자의 코딩 도우미(예: Claude Code)가 카탈로그를 검색하는 길이고, 로그 읽기는 `demo_scenes/logs`가 씁니다(아래 "MCP endpoint와 로그 권한"). 이 역할을 맡을 수 있는 주체는 `dev_principals`가 정합니다(기본값은 이 계정).

## 개념도에서의 위치

[개념도](../../docs/hosting-hub-concept.png)의 "개발팀"이 쓰는 권한입니다. 따로 그린 상자는 없습니다. ① "에이전트와 도구 검색"과 ② "에이전트 호스팅 신청"에서 카탈로그를 쓰는 권한이 여기에 있습니다. 에이전트를 만드는 동안 공유 도구를 부르게 하는 Cedar permit `shared_tool_read`는 전사 정책의 engine에 들어갑니다.

## 카탈로그 권한의 범위

개발팀 역할은 카탈로그에서 다섯 가지를 할 수 있습니다. 검색, 레코드 읽기, 레코드 만들기, 레코드 고치기, 승인 요청입니다. 에이전트를 올리는 흐름과 반려 뒤의 재신청이 이 역할로 돌아서 레코드를 고치는 권한이 필요합니다. 레코드의 ARN에는 무작위 ID가 들어가므로 IAM으로는 레코드를 만든 팀별로 권한을 나눌 수 없고, 이 권한은 Registry의 모든 레코드에 걸립니다. 그래서 이 역할로 다른 팀의 레코드나 플랫폼팀의 공유 도구 레코드(`parts-tools`)도 고칠 수 있습니다. 승인된 레코드를 고치면 새 DRAFT revision이 됩니다. AWS 문서([Record lifecycle](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/registry-record-lifecycle.html))에 따르면 새 revision이 승인될 때까지 승인된 revision이 계속 검색됩니다. 이 리포의 실행은 승인된 레코드를 고치는 경우를 확인하지 않았습니다. 이 역할은 다른 팀의 DRAFT, REJECTED 레코드도 읽을 수 있습니다. 운영 환경이라면 레코드에 주인 태그를 달고 IAM 조건으로 막거나, 레코드를 고치는 일을 플랫폼 쪽의 게시 함수가 맡게 해서 이 틈을 닫습니다.

## MCP endpoint와 로그 권한

Registry의 MCP endpoint(`https://agent-registry.<region>.api.aws/registry/<registry ID>/mcp`, SigV4로 서명하고 서비스 이름은 `agent-registry`)를 부르는 `agent-registry:InvokeRegistryMcp`는 허브의 Registry에만 줍니다. endpoint의 도구를 부를 때는 그 도구의 action도 있어야 합니다(검색 도구 `search_discoverable_registry_records`에는 이 역할이 이미 가진 `SearchDiscoverableRegistryRecords`). AWS 문서([Registry MCP endpoint](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/registry-mcp-endpoint.html), 2026-11-23에 읽었습니다)에 따르면 이 endpoint도 승인된 레코드만 돌려줍니다.

로그 권한은 읽기 둘뿐입니다. `logs:DescribeLogGroups`는 IAM이 로그 그룹으로 좁힐 수 없어서(자원 종류가 없습니다) 계정의 모든 로그 그룹의 이름을 볼 수 있습니다. 줄을 읽는 `logs:FilterLogEvents`는 허브 Runtime의 로그 그룹(`/aws/bedrock-agentcore/runtimes/<prefix>_*`)에만 줍니다. 한계가 있습니다. 이 샘플에서는 개발팀 역할 하나가 모든 팀에 쓰이므로, 개발자는 자기 팀의 에이전트만이 아니라 허브의 모든 에이전트의 로그 줄을 읽을 수 있습니다. harness 에이전트의 Runtime(`harness_<prefix>_<에이전트>`, 지금은 `spec_assistant`)의 로그는 이 역할이 읽지 못합니다. 운영 환경이라면 팀마다 역할을 두고 그 팀 에이전트의 로그 그룹만 줍니다.

2026-11-23에 시연 영상의 개발자 PC(`demo_video/tools/dev_pc`)에서 이 역할로 본 것입니다. MCP endpoint가 도구 넷(`search_discoverable_registry_records`, `search_discoverable_registry_records_paginated`, `list_discoverable_registry_records`, `batch_get_discoverable_registry_record`)을 보였고, Claude Code가 그 검색 도구로 `parts-tools`의 레코드를 찾았습니다(거부 없음). 로그는 `docs_adk`의 줄을 읽었고, `spec_assistant`(harness)의 로그 그룹에서는 `logs:FilterLogEvents`가 거부되었습니다. `search_discoverable_registry_records`가 아닌 MCP 도구(목록, 여러 레코드 읽기)를 부르는 것은 해 보지 않았습니다.

## 파일

| 파일 | 역할 |
|---|---|
| `terraform/` | 개발팀 역할(도구 게이트웨이의 `InvokeGateway`, 허브의 값 읽기(`ssm:GetParametersByPath`, `/<prefix>/platform`), Registry의 조회와 레코드 만들기와 승인 요청, Registry의 MCP endpoint(`InvokeRegistryMcp`), 허브 Runtime의 로그 읽기(`DescribeLogGroups`, `FilterLogEvents`))와 Cedar 정책 `shared_tool_read`(문장은 `company_policy/policy_templates/shared-tool-read.cedar`). 내보내는 값은 `dev_role_arn`, `dev_role_name`. 제출 버킷에 올리는 권한은 호스팅 심사(`hosting_review`)가 이 역할에 붙입니다. |
