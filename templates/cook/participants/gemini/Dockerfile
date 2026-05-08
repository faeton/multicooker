# Docker-mode scaffold for gemini participant.
# NOT WIRED UP IN v0.1. See HOWTO.md §Docker.

FROM node:22-slim

RUN npm install -g @google/gemini-cli

WORKDIR /work
ENV MULTIVARKA_IN_SANDBOX=1

CMD ["gemini", "--yolo", "-p", \
     "Read /work/BRIEF.md and complete the task. Reference material at /raw/."]
