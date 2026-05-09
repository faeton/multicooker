FROM node:22-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

# claude refuses --dangerously-skip-permissions when running as root.
# `node` user (uid=1000) ships with the node:22-slim image.
RUN mkdir -p /work /home/node/.claude \
 && chown -R node:node /work /home/node/.claude

COPY entrypoint.sh /usr/local/bin/mv-entrypoint
RUN chmod +x /usr/local/bin/mv-entrypoint

USER node
WORKDIR /work
ENV HOME=/home/node

ENTRYPOINT ["/usr/local/bin/mv-entrypoint"]
