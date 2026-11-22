"""The hub's settings outside Python: one rule for .env (make, publish.sh, reject.sh, rollout.sh, guardrail.sh, stop.sh,
resume.sh, usage.sh, e2e_hosting.py), the prefix rule, the model ID default, and the Makefile's destroy and test. Each
test runs on a copy of the files in a temporary folder, so it never reads or writes a real .env."""
import os
import pathlib
import re
import subprocess

import pytest

from platform_team.shared_code import config

ROOT = pathlib.Path(__file__).resolve().parents[1]
PUBLISH, REJECT = "dev_team/agent_template/publish.sh", "platform_team/hosting_review/reject.sh"
ROLLOUT = "platform_team/company_policy/rollout.sh"
GUARDRAIL = "platform_team/custom_guardrail/guardrail.sh"
STOP, RESUME = "platform_team/agent_stop/stop.sh", "platform_team/agent_stop/resume.sh"
USAGE = "platform_team/agent_monitoring/usage.sh"
RULE = "platform_team/shared_code/hub_env.sh"                  # every command sources it
SHOWN = "prefix=$DEMO_PREFIX region=$AWS_REGION model=$MODEL_ID loaded=${HUB_ENV_LOADED:-no} key=${AWS_ACCESS_KEY_ID:-none} token=${SOME_TOKEN:-none}"
DOTENV = ("DEMO_PREFIX=fromdotenv\nMODEL_ID=model-from-dotenv\nAWS_ACCESS_KEY_ID=key-of-the-dotenv\n"
          "SOME_TOKEN=do-not-export\n")


def _copy(tmp_path) -> tuple[pathlib.Path, dict]:
    """A copy of the Makefile and the seven commands, a stub uv that prints what it was given, and a clean environment:
    the shell sets the prefix, the region and an access key, and nothing says .env was read already."""
    repo = tmp_path / "repo"
    for name in ("Makefile", PUBLISH, REJECT, ROLLOUT, GUARDRAIL, STOP, RESUME, USAGE, RULE):
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_bytes((ROOT / name).read_bytes())
        (repo / name).chmod(0o755)
    (repo / "dev_team" / "some_agent").mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "uv").write_text(f'#!/usr/bin/env bash\necho "{SHOWN}"\n')
    (bin_dir / "uv").chmod(0o755)
    keep = {k: v for k, v in os.environ.items()
            if k not in ("HUB_ENV_LOADED", "DEMO_PREFIX", "AWS_REGION", "MODEL_ID", "SOME_TOKEN", "MAKEFLAGS", "MFLAGS")
            and not k.startswith("AWS_")}
    env = {**keep, "PATH": f"{bin_dir}:{os.environ['PATH']}", "DEMO_PREFIX": "fromshell", "AWS_REGION": "us-west-2",
           "AWS_ACCESS_KEY_ID": "key-of-the-shell"}
    return repo, env


def _run(cmd, repo, env, cwd=None):
    r = subprocess.run(cmd, cwd=cwd or repo, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout.strip().splitlines()[-1]


COMMANDS = {"publish.sh": lambda repo: [str(repo / PUBLISH), str(repo / "dev_team" / "some_agent")],
            "reject.sh": lambda repo: [str(repo / REJECT), "quality_agent", "a reason"],
            "rollout.sh": lambda repo: [str(repo / ROLLOUT), "guard_prompt", "report"],
            "guardrail.sh": lambda repo: [str(repo / GUARDRAIL), "status"],
            "stop.sh": lambda repo: [str(repo / STOP), "quality_agent", "--session", "a" * 36],
            "resume.sh": lambda repo: [str(repo / RESUME), "quality_agent"],
            "usage.sh": lambda repo: [str(repo / USAGE), "30"],
            "make publish": lambda repo: ["make", "-s", "publish", "AGENT=some_agent"]}


@pytest.mark.parametrize("command", COMMANDS)
def test_without_env_file_the_shell_gives_the_values(tmp_path, command):
    repo, env = _copy(tmp_path)
    out = _run(COMMANDS[command](repo), repo, env, cwd=tmp_path if command != "make publish" else repo)
    assert "prefix=fromshell region=us-west-2" in out and "key=key-of-the-shell" in out


@pytest.mark.parametrize("command", COMMANDS)
def test_env_file_gives_the_three_hub_values_only_and_wins_over_the_shell(tmp_path, command):
    repo, env = _copy(tmp_path)
    (repo / ".env").write_text(DOTENV)
    out = _run(COMMANDS[command](repo), repo, env, cwd=tmp_path if command != "make publish" else repo)
    assert "prefix=fromdotenv region=us-west-2 model=model-from-dotenv" in out
    assert "key=key-of-the-shell" in out and "token=none" in out          # credentials in .env are never exported


def test_a_value_on_the_make_command_line_wins_and_the_command_does_not_read_env_again(tmp_path):
    repo, env = _copy(tmp_path)
    (repo / ".env").write_text(DOTENV)
    out = _run(["make", "-s", "publish", "AGENT=some_agent", "DEMO_PREFIX=fromcmdline"], repo, env)
    assert "prefix=fromcmdline" in out and "model=model-from-dotenv" in out and "loaded=1" in out


@pytest.mark.parametrize("command", ["publish.sh", "reject.sh", "rollout.sh", "guardrail.sh", "stop.sh", "resume.sh",
                                     "usage.sh"])
def test_a_command_told_env_was_read_already_does_not_read_it(tmp_path, command):
    repo, env = _copy(tmp_path)
    (repo / ".env").write_text(DOTENV)
    out = _run(COMMANDS[command](repo), repo, {**env, "HUB_ENV_LOADED": "1", "DEMO_PREFIX": "chosen"}, cwd=tmp_path)
    assert "prefix=chosen" in out and "model=model-from-dotenv" not in out


def test_the_e2e_script_reads_env_by_the_same_rule(tmp_path):
    dotenv = tmp_path / ".env"
    shell = {"DEMO_PREFIX": "fromshell", "AWS_REGION": "us-west-2", "AWS_ACCESS_KEY_ID": "key-of-the-shell"}
    assert config.env_file_updates(shell, dotenv) == {"HUB_ENV_LOADED": "1"}          # no .env: the shell's values
    dotenv.write_text("# a comment\n" + DOTENV + "AWS_REGION=us-east-2\nDEMO_PREFIX=last\n")
    assert config.env_file_updates(shell, dotenv) == {"DEMO_PREFIX": "last", "MODEL_ID": "model-from-dotenv",
                                                     "AWS_REGION": "us-east-2", "HUB_ENV_LOADED": "1"}
    assert config.env_file_updates({**shell, "HUB_ENV_LOADED": "1"}, dotenv) == {}     # make (or a caller) read it


def test_an_empty_line_in_the_env_file_is_no_value_for_any_reader(tmp_path):
    """shell DEMO_PREFIX=fromshell, .env line `DEMO_PREFIX=`: make, publish.sh, reject.sh, rollout.sh, guardrail.sh,
    stop.sh, resume.sh, usage.sh and env_file_updates all use fromshell."""
    repo, env = _copy(tmp_path)
    (repo / ".env").write_text("DEMO_PREFIX=\nMODEL_ID=model-from-dotenv\n")
    for command in COMMANDS:
        out = _run(COMMANDS[command](repo), repo, env, cwd=tmp_path if command != "make publish" else repo)
        assert "prefix=fromshell" in out and "model=model-from-dotenv" in out, command
    updates = config.env_file_updates(env, repo / ".env")
    assert "DEMO_PREFIX" not in updates and updates["MODEL_ID"] == "model-from-dotenv"
    # an empty line after a filled one does not erase it: an empty line is the same as no line
    (repo / ".env").write_text("DEMO_PREFIX=fromdotenv\nDEMO_PREFIX=\n")
    assert config.env_file_updates(env, repo / ".env")["DEMO_PREFIX"] == "fromdotenv"
    for command in COMMANDS:
        out = _run(COMMANDS[command](repo), repo, env, cwd=tmp_path if command != "make publish" else repo)
        assert "prefix=fromdotenv" in out, command


def test_nothing_else_from_the_env_file_reaches_stdout_or_stderr(tmp_path):
    """.env holds SOME_TOKEN=do-not-export: the value is in neither stream of publish.sh, reject.sh, rollout.sh,
    guardrail.sh, stop.sh, resume.sh, usage.sh or `make publish`."""
    repo, env = _copy(tmp_path)
    (repo / ".env").write_text(DOTENV)
    for command in COMMANDS:
        r = subprocess.run(COMMANDS[command](repo), cwd=tmp_path if command != "make publish" else repo, env=env,
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "do-not-export" not in r.stdout + r.stderr, command


def test_the_e2e_script_applies_the_rule_before_it_reads_its_settings():
    text = (ROOT / "e2e_checks" / "e2e_hosting.py").read_text()
    main = text[text.index("def main()"):]
    assert main.index("env_file_updates(") < main.index("Settings.from_env()")


# ------------------------------------------------------------------ the prefix, the model ID, make destroy, make test

@pytest.mark.parametrize("prefix", ["my-hub", "hub_1", "Hub", "h", "abcdefghijk", "1hub", "", "hub "])
def test_a_prefix_the_names_cannot_carry_is_refused(prefix):
    with pytest.raises(ValueError, match="prefix .* must be 2 to 10 lower-case letters or digits"):
        config.Settings(prefix=prefix)


@pytest.mark.parametrize("prefix", ["hub", "hubx", "h2", "abcdefghij"])
def test_a_prefix_of_lower_case_letters_and_digits_is_taken(prefix):
    assert config.Settings(prefix=prefix).prefix == prefix


def test_terraform_refuses_the_same_prefixes():
    text = (ROOT / "platform_team" / "terraform" / "variables.tf").read_text()
    block = re.search(r'variable\s+"prefix"\s*{(.*?)\n}\n', text, re.S).group(1)
    rule = re.search(r'condition\s*=\s*can\(regex\("(.+?)", var\.prefix\)\)', block).group(1)
    assert rule == f"^{config.PREFIX_PATTERN}$"


def test_the_model_id_default_is_the_same_in_every_place_it_is_written():
    makefile = re.search(r"^MODEL_ID \?= (\S+)$", (ROOT / "Makefile").read_text(), re.M).group(1)
    example = re.search(r"^MODEL_ID=(\S+)$", (ROOT / ".env.example").read_text(), re.M).group(1)
    platform = (ROOT / "platform_team" / "terraform" / "variables.tf").read_text()
    tf = re.search(r'variable\s+"model_id"\s*{[^}]*default\s*=\s*"([^"]+)"', platform).group(1)
    assert makefile == example == tf == config.DEFAULT_MODEL_ID
    assert f"`{config.DEFAULT_MODEL_ID}`" in (ROOT / "README.md").read_text()
    review = (ROOT / "platform_team" / "hosting_review" / "terraform" / "variables.tf").read_text()
    assert "default" not in re.search(r'variable\s+"model_id"\s*{(.*?)\n}\n', review, re.S).group(1)   # the module's copy


@pytest.mark.parametrize("approve", ["1", "0"])
def test_make_destroy_initialises_terraform_before_it_plans_or_destroys(approve):
    r = subprocess.run(["make", "-n", "destroy", f"AUTO_APPROVE={approve}"], cwd=ROOT, capture_output=True, text=True,
                       env={k: v for k, v in os.environ.items() if k not in ("MAKEFLAGS", "MFLAGS")})
    lines = r.stdout.splitlines()
    init = next(i for i, line in enumerate(lines) if "init -input=false" in line)
    first_tf = next(i for i, line in enumerate(lines) if re.search(r"terraform -chdir=\S+ (plan|destroy)", line))
    assert init < first_tf


def test_make_destroy_asks_about_the_catalog_records_too():
    r = subprocess.run(["make", "-n", "destroy", "AUTO_APPROVE=0"], cwd=ROOT, capture_output=True, text=True,
                       env={k: v for k, v in os.environ.items() if k not in ("MAKEFLAGS", "MFLAGS")})
    assert "and every other record left in the catalog" in r.stdout


def _destroy_lines(approve):
    r = subprocess.run(["make", "-n", "destroy", f"AUTO_APPROVE={approve}"], cwd=ROOT, capture_output=True, text=True,
                       env={k: v for k, v in os.environ.items() if k not in ("MAKEFLAGS", "MFLAGS")})
    return r.stdout.splitlines()


@pytest.mark.parametrize("approve", ["1", "0"])
def test_make_destroy_forgets_the_company_policy_modes_before_it_cleans_the_agents(approve):
    """An approval after the cleanup started gives the agent no company policy: the modes go first. A failure stops
    the destroy, and without AUTO_APPROVE=1 the question comes before it."""
    lines = _destroy_lines(approve)
    forget = next(i for i, line in enumerate(lines) if "platform_team.company_policy.policy_rollout --forget" in line)
    clean = next(i for i, line in enumerate(lines) if "platform_team.hosting_review.agent_cleanup ||" in line)
    assert forget < clean and "|| {" in lines[forget] and "exit 1" in lines[forget]
    asked = [i for i, line in enumerate(lines) if "read answer" in line]
    assert asked == ([] if approve == "1" else [asked[0]]) and all(i < forget for i in asked)


def test_make_destroy_asks_about_the_company_policy_modes_too():
    assert "the modes of the company policies" in "\n".join(_destroy_lines("0"))


def test_make_test_runs_the_unit_tests_with_every_warning_an_error():
    r = subprocess.run(["make", "-n", "test"], cwd=ROOT, capture_output=True, text=True,
                       env={k: v for k, v in os.environ.items() if k not in ("MAKEFLAGS", "MFLAGS")})
    assert r.stdout.splitlines() == ["uv run pytest tests -q -W error"]


@pytest.mark.parametrize("approve", ["1", "0"])
def test_make_destroy_detaches_the_custom_guardrail_before_anything_else_changes(approve):
    """The gateway never points at a deleted Lambda: the interceptor is detached before terraform destroy (on a hub
    that is not deployed the command does nothing and succeeds). A failure stops the destroy; without AUTO_APPROVE=1
    the question comes before it."""
    lines = _destroy_lines(approve)
    detach = next(i for i, line in enumerate(lines) if "platform_team.custom_guardrail.guardrail_attach detach" in line)
    forget = next(i for i, line in enumerate(lines) if "platform_team.company_policy.policy_rollout --forget" in line)
    destroy = next(i for i, line in enumerate(lines) if re.search(r"terraform -chdir=\S+ destroy", line))
    assert detach < forget < destroy and "|| {" in lines[detach] and "exit 1" in lines[detach]
    asked = [i for i, line in enumerate(lines) if "read answer" in line]
    assert all(i < detach for i in asked)
    if approve == "0":
        assert "Detach the custom guardrail from the agent gateway" in lines[asked[0]]


def test_the_guardrail_command_says_its_usage_without_arguments(tmp_path):
    repo, env = _copy(tmp_path)
    r = subprocess.run([str(repo / GUARDRAIL)], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert r.returncode == 2 and "usage: guardrail.sh attach|detach|status" in r.stderr


@pytest.mark.parametrize("argv, usage", [([STOP], "usage: stop.sh <agent> [--session <ID> ...]"),
                                         ([RESUME], "usage: resume.sh <agent>"),
                                         ([RESUME, "quality_agent", "now"], "usage: resume.sh <agent>")])
def test_the_stop_and_resume_commands_say_their_usage_for_other_arguments(tmp_path, argv, usage):
    repo, env = _copy(tmp_path)
    r = subprocess.run([str(repo / argv[0]), *argv[1:]], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert r.returncode == 2 and usage in r.stderr and "prefix=" not in r.stdout          # uv was not run
