# Per-cook gemini image. See templates/base/gemini/Dockerfile for the heavy bits.
FROM mc-base-gemini:latest

USER root
COPY entrypoint.sh /usr/local/bin/mc-entrypoint
RUN chmod +x /usr/local/bin/mc-entrypoint
USER node

ENTRYPOINT ["/usr/local/bin/mc-entrypoint"]
