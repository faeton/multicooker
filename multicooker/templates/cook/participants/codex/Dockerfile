# Per-cook codex image. See templates/base/codex/Dockerfile for the heavy bits.
FROM mc-base-codex:latest

USER root
COPY entrypoint.sh /usr/local/bin/mc-entrypoint
RUN chmod +x /usr/local/bin/mc-entrypoint
USER node

ENTRYPOINT ["/usr/local/bin/mc-entrypoint"]
