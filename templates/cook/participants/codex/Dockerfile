FROM node:22-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @openai/codex

RUN mkdir -p /work /home/node/.codex \
 && chown -R node:node /work /home/node/.codex

COPY entrypoint.sh /usr/local/bin/mv-entrypoint
RUN chmod +x /usr/local/bin/mv-entrypoint

USER node
WORKDIR /work
ENV HOME=/home/node

ENTRYPOINT ["/usr/local/bin/mv-entrypoint"]
