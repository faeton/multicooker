# Per-cook agy image. See templates/base/agy/Dockerfile for the heavy bits.
FROM mc-base-agy:latest

USER root
COPY entrypoint.sh /usr/local/bin/mc-entrypoint
RUN chmod +x /usr/local/bin/mc-entrypoint
USER node

ENTRYPOINT ["/usr/local/bin/mc-entrypoint"]
