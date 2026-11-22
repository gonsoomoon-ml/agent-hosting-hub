# Targets run from the repo root. AGENT=<name> selects a developer-team agent.
# Region, prefix and model come from .env (see .env.example) or the shell. Python reads them as AWS_REGION,
# DEMO_PREFIX and MODEL_ID; Terraform gets the same values as TF_VAR_region, TF_VAR_prefix and TF_VAR_model_id.
-include .env
AWS_REGION ?= us-west-2
DEMO_PREFIX ?= hub
MODEL_ID ?= us.anthropic.claude-haiku-4-5-20251001-v1:0
export AWS_REGION DEMO_PREFIX MODEL_ID
export TF_VAR_region = $(AWS_REGION)
export TF_VAR_prefix = $(DEMO_PREFIX)
export TF_VAR_model_id = $(MODEL_ID)
TF = terraform -chdir=platform_team/terraform

.PHONY: test package deploy seed destroy publish e2e

test:
	uv run pytest tests -q

# build/platform_team.zip and build/tool_schemas.json; Terraform reads them (even to destroy)
package:
	uv run python -m platform_team.shared_code.code_package

deploy: package
	$(TF) init -input=false
	$(TF) apply -input=false -auto-approve

seed:
	uv run python -m platform_team.agent_catalog.seed_catalog

# The seeded record is outside Terraform's state, and a registry with records cannot be deleted: remove it first.
destroy: package
	uv run python -m platform_team.agent_catalog.seed_catalog --remove
	$(TF) destroy -input=false -auto-approve

publish:
	uv run python -m dev_team.publish $(AGENT)

e2e:
	uv run pytest e2e_checks -q
