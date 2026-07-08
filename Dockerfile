# CICD Reviewer image — a heaven agent that reviews PRs / opens PRs, configured entirely
# by the cicd_aios AIOS baked in at /cicd_aios. The agent's cwd is /cicd_aios so
# heaven-framework's resolve_devdirs auto-loads /cicd_aios/.claude/rules + .claude/skills
# into its system prompt. The repo under review is mounted/checked-out at /repo.
#
# Build context is THIS directory (automation/cicd-reviewer/). The build step first stages
# the monorepo's heaven-framework 0.1.30 into ./_vendor/heaven-framework (see build workflow),
# because it lives outside this context.
FROM python:3.11-slim

# git + gh (GitHub CLI) for the review/PR git ops
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates curl gnupg && \
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        -o /usr/share/keyrings/githubcli-archive-keyring.gpg && \
    chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list && \
    apt-get update && apt-get install -y --no-install-recommends gh && \
    rm -rf /var/lib/apt/lists/*

# heaven-framework 0.1.30 base deps, pinned. google-adk/genai (forces pydantic>=2.12, ADK
# dead-by-default) and skill-manager-mcp (we use dep-free devdir skill loading, Anthropic/MiniMax
# path only) are intentionally OMITTED. Installed WITH their transitive deps so the heaven
# install below can be --no-deps. Provider classes ChatOpenAI/Groq/DeepSeek are imported at
# unified_chat module load, so those langchain providers are required even for the Anthropic path.
RUN pip install --no-cache-dir \
    'pydantic==2.10.6' 'langchain-core==0.3.84' 'langchain==0.3.28' \
    'langchain-anthropic==0.3.13' 'langchain-openai==0.3.22' \
    'langchain-groq==0.2.4' 'langchain-deepseek==0.1.2' \
    'langgraph==0.2.60' 'litellm==1.80.0' \
    'requests==2.33.1' 'httpx==0.28.1' 'fastmcp==2.9.0' 'tiktoken>=0.5.0'

# heaven-framework itself, WITHOUT deps (so pip cannot re-resolve/upgrade the pins above —
# Isaac: "get the new version no deps"). _vendor/heaven-framework is the synced 0.1.30 copy.
COPY _vendor/heaven-framework /opt/heaven-framework
RUN pip install --no-cache-dir --no-deps /opt/heaven-framework && \
    python3 -c "import heaven_base; print('heaven-framework', heaven_base.__version__, 'import OK')"

# The reviewer AIOS (its .claude/rules + .claude/skills ARE the agent's config) + the agent
COPY cicd_aios /cicd_aios
COPY ci_agent.py /cicd_aios/ci_agent.py
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV HEAVEN_DATA_DIR=/tmp/heaven_data PYTHONUNBUFFERED=1
WORKDIR /cicd_aios
ENTRYPOINT ["/entrypoint.sh"]
