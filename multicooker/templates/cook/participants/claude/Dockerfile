# Per-cook claude image. Heavy bits live in mc-base-claude; this image just
# layers in the entrypoint. mc-base-claude is built once by
# `multicooker build-base` (cook auto-builds it if missing).
FROM mc-base-claude:latest

USER root
COPY entrypoint.sh /usr/local/bin/mc-entrypoint
RUN chmod +x /usr/local/bin/mc-entrypoint
USER node

ENTRYPOINT ["/usr/local/bin/mc-entrypoint"]
