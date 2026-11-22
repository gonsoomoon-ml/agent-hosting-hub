# 도구 게이트웨이

에이전트와 개발자가 사내 도구를 부르는 MCP 게이트웨이(`<prefix>-tools`)다. Cedar permit이 허용한 도구 호출만 통과시킨다. 허용되지 않은 도구는 `tools/list`에도 보이지 않는다. target은 `sample_tools/tool_schema.py`의 `TARGETS`에서 하나씩(`Quality`, `Parts`, `Release`) 만든다. 에이전트에게 도구는 `<Target>___<tool>`이라는 이름으로 보인다.

## 개념도에서의 위치

"도구 게이트웨이: 허용된 도구 호출만 통과" 상자다. ⑧ "도구 호출"을 받고, ⑨ "허용된 호출만 전달"에서 permit이 있는 호출만 사내 도구로 넘긴다.

## 파일

| 파일 | 역할 |
|---|---|
| `terraform/` | 게이트웨이, 그 역할 `<prefix>-tools-role`(도구 Lambda 호출, policy engine), 도구 target(`TARGETS`의 target마다 하나, 스키마는 `build/tool_schemas.json`). 내보내는 값은 `gateway_id`, `gateway_arn`, `gateway_url`. |
