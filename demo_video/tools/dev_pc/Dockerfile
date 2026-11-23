# The developer PC of the demo video: Claude Code (on Amazon Bedrock), Python with uv, the AWS CLI and the proxy for
# the catalog's MCP endpoint, at pinned versions. Built by `run.sh build` with no build context: no file of the PC
# that builds it goes into a layer. Credentials never go into the image; run.sh mounts them when the container starts.
FROM node:22.18.0-bookworm-slim

ARG CLAUDE_CODE_VERSION=2.1.330
ARG MCP_PROXY_VERSION=2.0.0
ARG AWS_CLI_VERSION=2.31.10
ARG PYTHON_VERSION=3.13
ARG DEV_UID=1000

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl unzip jq git less procps iproute2 \
 && rm -rf /var/lib/apt/lists/*

# AWS CLI v2 from AWS's own download, for this machine's architecture
RUN curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-$(uname -m)-${AWS_CLI_VERSION}.zip" -o /tmp/awscli.zip \
 && unzip -q /tmp/awscli.zip -d /tmp \
 && /tmp/aws/install \
 && rm -rf /tmp/aws /tmp/awscli.zip

# uv, and the Python it manages (kept in the image, so no take waits for a download)
COPY --from=ghcr.io/astral-sh/uv:0.10.8 /uv /uvx /usr/local/bin/
ENV UV_PYTHON_INSTALL_DIR=/opt/uv/python UV_TOOL_DIR=/opt/uv/tools UV_TOOL_BIN_DIR=/usr/local/bin
RUN uv python install "${PYTHON_VERSION}" \
 && uv tool install "mcp-proxy-for-aws==${MCP_PROXY_VERSION}" \
 && chmod -R a+rX /opt/uv

# Claude Code at the pinned version; it never updates itself here (DISABLE_AUTOUPDATER in the project's settings)
RUN npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
 && npm cache clean --force

# The developer: user dev, the same user id as the PC that runs the container (the home is a folder of that PC)
RUN userdel -r node \
 && useradd --uid "${DEV_UID}" --create-home --shell /bin/bash dev \
 && printf '%s\n' "PS1='개발자 \$ '" >> /etc/bash.bashrc

# The scene commands are found last: a file in the editable checkout never shadows ls, cat, uv or ip.
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8 UV_PYTHON_DOWNLOADS=never AWS_PAGER="" NPM_CONFIG_UPDATE_NOTIFIER=false \
    PATH=$PATH:/home/dev/work/demo_scenes
USER dev
WORKDIR /home/dev/work
CMD ["sleep", "infinity"]
