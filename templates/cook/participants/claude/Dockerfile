# Per-cook claude image. Heavy bits live in mv-base-claude; this image just
# layers in the entrypoint. mv-base-claude is built once by
# `multivarka build-base` (cook auto-builds it if missing).
FROM mv-base-claude:latest

USER root
COPY entrypoint.sh /usr/local/bin/mv-entrypoint
RUN chmod +x /usr/local/bin/mv-entrypoint
USER node

ENTRYPOINT ["/usr/local/bin/mv-entrypoint"]
