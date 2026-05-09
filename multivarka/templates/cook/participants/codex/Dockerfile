# Per-cook codex image. See templates/base/codex/Dockerfile for the heavy bits.
FROM mv-base-codex:latest

USER root
COPY entrypoint.sh /usr/local/bin/mv-entrypoint
RUN chmod +x /usr/local/bin/mv-entrypoint
USER node

ENTRYPOINT ["/usr/local/bin/mv-entrypoint"]
