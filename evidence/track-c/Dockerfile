FROM node:20-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git tmux python3 python3-pip python3-venv ca-certificates jq procps \
    && rm -rf /var/lib/apt/lists/*

ARG CLAUDE_CODE_VERSION
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}

RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install pydantic>=2.0

RUN mkdir -p /workspace/test-project && cd /workspace/test-project && \
    git init && git config user.email "test@test.com" && \
    git config user.name "Test" && echo "# Test" > README.md && \
    git add . && git commit -m "init"

ENV TERM=xterm-256color PATH="/opt/venv/bin:$PATH"
WORKDIR /workspace/test-project
CMD ["bash"]
