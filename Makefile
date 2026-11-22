# Targets run from the repo root. AGENT=<name> selects a developer-team agent.
.PHONY: test package deploy seed destroy publish e2e

test:
	uv run pytest tests -q

package:
	uv run python -m platform_team.shared_code.package

deploy: package
	terraform -chdir=platform_team/terraform init
	terraform -chdir=platform_team/terraform apply

seed:
	uv run python -m platform_team.seed

destroy:
	uv run python -m platform_team.destroy_agents
	terraform -chdir=platform_team/terraform destroy

publish:
	uv run python -m dev_team.publish $(AGENT)

e2e:
	uv run pytest e2e_checks -q
