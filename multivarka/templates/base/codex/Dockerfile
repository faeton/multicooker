# mv-base-codex — shared base image for codex participants/judges.
FROM node:22-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @openai/codex

RUN mkdir -p /work /home/node/.codex \
 && chown -R node:node /work /home/node/.codex

USER node
WORKDIR /work
ENV HOME=/home/node
