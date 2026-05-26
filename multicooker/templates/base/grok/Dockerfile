# mc-base-grok — shared base image for grok (xAI CLI) participants/judges.
# The grok installer (https://x.ai/cli/install.sh) detects the OS/arch, drops
# a static binary into $HOME/.grok/downloads/, symlinks $HOME/.grok/bin/grok,
# and tries to edit shell rc files. We invoke it non-interactively as `node`
# and put ~/.grok/bin on PATH ourselves.
#
# Pinned to GROK_VERSION for reproducibility; bump after smoke-testing a new
# release. Override at build time: --build-arg GROK_VERSION=0.1.230
FROM node:22-slim

ARG GROK_VERSION=0.1.220

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /work /home/node/.grok \
 && chown -R node:node /work /home/node/.grok

USER node
WORKDIR /home/node
ENV HOME=/home/node

# Install script writes to $HOME/.grok/{downloads,bin} and appends to ~/.bashrc.
# The rc edit is harmless (we set PATH via ENV below) and the install dir
# stays writable for runtime session/trust files.
RUN curl -fsSL https://x.ai/cli/install.sh | bash -s "$GROK_VERSION"

ENV PATH=/home/node/.grok/bin:$PATH

WORKDIR /work
