# dummy flavor — no LLM, no auth, no network. Used for integration smoke
# tests of the cook→judge→report pipeline without burning subscription
# credits or hitting external APIs.
#
# Self-contained (does not derive from mc-base-*) because the image is
# already small and the whole point is to be trivially reproducible in CI.
FROM alpine:3

RUN adduser -D -u 1000 mv \
 && mkdir -p /work \
 && chown mv:mv /work

COPY entrypoint.sh /usr/local/bin/mc-entrypoint
RUN chmod +x /usr/local/bin/mc-entrypoint

USER mv
WORKDIR /work
ENV HOME=/home/mv

ENTRYPOINT ["/usr/local/bin/mc-entrypoint"]
