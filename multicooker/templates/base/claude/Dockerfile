# mc-base-claude — shared base image for claude participants/judges.
# Built once with `multicooker build-base` (or auto on first cook). Per-cook
# images derive from this with `FROM mc-base-claude:latest` and only add
# the entrypoint, so cook builds become near-instant.
FROM node:22-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

# claude refuses --dangerously-skip-permissions when running as root.
# `node` user (uid=1000) ships with the node:22-slim image.
RUN mkdir -p /work /home/node/.claude \
 && chown -R node:node /work /home/node/.claude

USER node
WORKDIR /work
ENV HOME=/home/node
