# Targets run from the repo root. AGENT=<name> selects a developer-team agent.
# Region, prefix and model: Python reads them as AWS_REGION, DEMO_PREFIX and MODEL_ID; Terraform gets the same
# values as TF_VAR_region, TF_VAR_prefix and TF_VAR_model_id. Where they come from (README, ".env"): a value on the
# make command line, else the line NAME=value in .env (see .env.example), else the shell, else the default below.
# Only these three lines of .env are read; nothing else in it becomes a make variable or is exported.
# HUB_ENV_LOADED=1 tells the commands make runs (publish.sh, e2e_hosting.py) that the values are chosen already.
HUB_VARIABLES := AWS_REGION DEMO_PREFIX MODEL_ID
dotenv = $(if $(wildcard .env),$(shell sed -n 's/^$(1)=//p' .env | tail -n 1))
$(foreach v,$(HUB_VARIABLES),$(if $(call dotenv,$(v)),$(eval $(v) := $(call dotenv,$(v)))))
AWS_REGION ?= us-west-2
DEMO_PREFIX ?= hub
MODEL_ID ?= us.anthropic.claude-haiku-4-5-20251001-v1:0
export AWS_REGION DEMO_PREFIX MODEL_ID
export HUB_ENV_LOADED := 1
export TF_VAR_region = $(AWS_REGION)
export TF_VAR_prefix = $(DEMO_PREFIX)
export TF_VAR_model_id = $(MODEL_ID)
TF = terraform -chdir=platform_team/terraform
SEED = uv run python -m platform_team.agent_catalog.seed_catalog
CLEAN = uv run python -m platform_team.hosting_review.agent_cleanup
# deploy and destroy show the plan and ask before they change the account. AUTO_APPROVE=1 skips the question
# (check scripts, scripted runs): AUTO_APPROVE=1 make deploy
APPROVE = $(if $(filter 1,$(AUTO_APPROVE)),-auto-approve,)

.PHONY: test package deploy seed destroy publish e2e

test:
	uv run pytest tests -q

# build/platform_team.zip and build/tool_schemas.json; Terraform reads them (even to destroy)
package:
	uv run python -m platform_team.shared_code.code_package

deploy: package
	$(TF) init -input=false
	$(TF) apply $(APPROVE)

seed:
	$(SEED)

# Outside Terraform's state: what the hosting review made for each agent (policies, gateway target, Runtime stack and
# logs, execution role, SSM values), the agents' catalog records and the seeded record. An agent role keeps the
# boundary policy from being deleted, and a registry with records cannot be deleted: they all go first, the agents
# before the seed. Then `agent_cleanup --records` deletes any record still in the hub's registry (another type, a name
# the rules refuse) and prints each one. If a step fails, terraform destroy does not run.
# So the question comes before anything changes: the destroy plan, then yes or no. AUTO_APPROVE=1 skips it.
# Last, check_cleanup lists what of the hub is still in the account (it reads only) and ends with `still present: ...`.
destroy: package
	$(TF) init -input=false
ifneq ($(AUTO_APPROVE),1)
	$(TF) plan -destroy
	@printf "Destroy everything above, every hosted agent with its catalog record, and the seeded catalog record? Only 'yes' is accepted: "; read answer; \
	  [ "$$answer" = yes ] || { echo "Destroy cancelled."; exit 1; }
endif
	@$(CLEAN) || { echo "Destroy stopped before terraform destroy: the agents were not all removed (see the line above). Fix that and run make destroy again."; exit 1; }
	$(SEED) --remove
	$(CLEAN) --records
	$(TF) destroy -auto-approve
	uv run python e2e_checks/check_cleanup.py

publish:
	dev_team/agent_template/publish.sh dev_team/$(AGENT)

# Flow 1 (hosting) from end to end on the deployed hub. The last run took 26 minutes, 8 of them removing the two
# approved agents an earlier run had left.
# The log goes to e2e_checks/last-run.log (not committed: *.log).
e2e:
	bash -o pipefail -c 'uv run python e2e_checks/e2e_hosting.py 2>&1 | tee e2e_checks/last-run.log'
