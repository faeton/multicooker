# Docker-mode scaffold for codex participant.
# NOT WIRED UP IN v0.1. See HOWTO.md §Docker.

FROM node:22-slim

RUN npm install -g @openai/codex

WORKDIR /work
ENV MULTIVARKA_IN_SANDBOX=1

CMD ["codex", "exec", \
     "--cd", "/work", \
     "--dangerously-bypass-approvals-and-sandbox", \
     "--skip-git-repo-check", \
     "Read /work/BRIEF.md and complete the task. Reference material at /raw/."]
