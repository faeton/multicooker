# mc-base-gemini — shared base image for gemini participants/judges.
FROM node:22-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @google/gemini-cli

RUN mkdir -p /work /home/node/.gemini \
 && chown -R node:node /work /home/node/.gemini

USER node
WORKDIR /work
ENV HOME=/home/node
