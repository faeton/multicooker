# Docker-mode scaffold for claude participant.
# NOT WIRED UP IN v0.1. Host-mode is the supported path. See HOWTO.md §Docker.
#
# When wiring this up:
# 1. Build with: `docker build -t multivarka-claude .`
# 2. Run with:
#    docker run --rm \
#      -e ANTHROPIC_API_KEY \
#      -v $(pwd)/work/claude:/work \
#      -v $(pwd)/raw:/raw:ro \
#      -v $(pwd)/BRIEF.md:/work/BRIEF.md:ro \
#      multivarka-claude
# 3. The CLI is invoked from /work and writes to /work/out/.

FROM node:22-slim

RUN npm install -g @anthropic-ai/claude-code

WORKDIR /work
ENV MULTIVARKA_IN_SANDBOX=1

CMD ["claude", "--print", "--dangerously-skip-permissions", \
     "Read /work/BRIEF.md and complete the task. Reference material at /raw/.", \
     "--add-dir", "/work"]
