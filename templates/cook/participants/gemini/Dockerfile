# Per-cook gemini image. See templates/base/gemini/Dockerfile for the heavy bits.
FROM mv-base-gemini:latest

USER root
COPY entrypoint.sh /usr/local/bin/mv-entrypoint
RUN chmod +x /usr/local/bin/mv-entrypoint
USER node

ENTRYPOINT ["/usr/local/bin/mv-entrypoint"]
