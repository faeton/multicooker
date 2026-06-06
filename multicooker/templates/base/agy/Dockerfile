# mc-base-agy — shared base image for agy (Google Antigravity CLI) participants/judges.
# agy is the successor to gemini-cli; it ships as a standalone binary (not npm)
# and reuses ~/.gemini for OAuth creds. The install script auto-detects
# linux/{amd64,arm64} + glibc/musl and drops the binary in ~/.local/bin/agy.
FROM debian:12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/*

# Run as uid 1000 'node' to match the compose mounts (/home/node) and the
# hardening user (1000:1000), same convention as the claude base.
RUN groupadd -g 1000 node && useradd -g node -u 1000 -m -s /bin/bash node \
 && mkdir -p /work /home/node/.gemini \
 && chown -R node:node /work /home/node/.gemini

USER node
ENV HOME=/home/node
ENV PATH=/home/node/.local/bin:$PATH
# agy phones home for self-updates on first run; pin to the build-time version
# so cooks are reproducible and don't fetch a new binary mid-run.
ENV AGY_CLI_DISABLE_AUTO_UPDATE=1

# Install the agy binary into ~/.local/bin (no root needed). The script also
# configures shell profiles; harmless during build.
RUN curl -fsSL https://antigravity.google/cli/install.sh | bash

WORKDIR /work
