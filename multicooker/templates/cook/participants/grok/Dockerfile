# Per-cook grok image. See templates/base/grok/Dockerfile for the heavy bits.
FROM mc-base-grok:latest

USER root
COPY entrypoint.sh /usr/local/bin/mc-entrypoint
RUN chmod +x /usr/local/bin/mc-entrypoint
USER node

ENTRYPOINT ["/usr/local/bin/mc-entrypoint"]
