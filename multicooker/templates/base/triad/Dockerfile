# mc-base-triad — shared base image for the "triad" flavor: a single cell that
# runs Claude (the LEAD ENGINEER) with Codex and Grok installed alongside as
# in-cell reviewers Claude consults via Bash. All three CLIs live here; creds
# for all three are bind-mounted by compose (see compose_render._auth_volumes).
#
# Built once with `multicooker build-base triad` (or auto on first cook that
# uses it). Per-cook image just layers the entrypoint on top.
#
# Combines the install steps of mc-base-{claude,codex,grok}. Pinned grok
# version matches templates/base/grok/Dockerfile — bump in lockstep.
FROM node:22-slim

ARG GROK_VERSION=0.1.220

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Claude (lead) + Codex (reviewer) from npm.
RUN npm install -g @anthropic-ai/claude-code @openai/codex

# claude refuses --dangerously-skip-permissions as root; node (uid=1000) ships
# with node:22-slim. Pre-create all three cred mountpoints.
RUN mkdir -p /work /home/node/.claude /home/node/.codex /home/node/.grok \
 && chown -R node:node /work /home/node/.claude /home/node/.codex /home/node/.grok

USER node
WORKDIR /home/node
ENV HOME=/home/node

# Grok (reviewer): static binary into ~/.grok/bin via the xAI installer, run
# non-interactively as node. We set PATH ourselves (the rc edit is ignored).
RUN curl -fsSL https://x.ai/cli/install.sh | bash -s "$GROK_VERSION"
ENV PATH=/home/node/.grok/bin:$PATH

WORKDIR /work
