# Per-cook triad image. Heavy bits (claude + codex + grok CLIs) live in
# mc-base-triad; this image just layers in the entrypoint, so cook builds stay
# near-instant. mc-base-triad is built by `multicooker build-base triad`
# (cook auto-builds it if missing).
FROM mc-base-triad:latest

USER root
COPY entrypoint.sh /usr/local/bin/mc-entrypoint
RUN chmod +x /usr/local/bin/mc-entrypoint
USER node

ENTRYPOINT ["/usr/local/bin/mc-entrypoint"]
