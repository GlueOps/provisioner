FROM jetpackio/devbox:0.13.7@sha256:6295e9cde3d73f3c1b5316533f0954cb26c6576a069c35930b717a0b4571ca99

# Installing your devbox project
WORKDIR /code
USER root:root

RUN mkdir -p /code && chown ${DEVBOX_USER}:${DEVBOX_USER} /code
RUN mkdir -p /var/run/tailscale /var/cache/tailscale /var/lib/tailscale
RUN chown ${DEVBOX_USER}:${DEVBOX_USER} /var/run/tailscale /var/cache/tailscale /var/lib/tailscale
USER ${DEVBOX_USER}:${DEVBOX_USER}
COPY --chown=${DEVBOX_USER}:${DEVBOX_USER} devbox.json devbox.json
COPY --chown=${DEVBOX_USER}:${DEVBOX_USER} devbox.lock devbox.lock
COPY --chown=${DEVBOX_USER}:${DEVBOX_USER} Pipfile Pipfile
COPY --chown=${DEVBOX_USER}:${DEVBOX_USER} Pipfile.lock Pipfile.lock

RUN devbox run -- echo "Installed Packages."
RUN devbox run pipenv install
# https://stackoverflow.com/questions/34370962/no-module-named-cffi-backend
RUN devbox run fix_cffi 

COPY --chown=${DEVBOX_USER}:${DEVBOX_USER} app/ /code/app

CMD [ "devbox", "run", "k8s"]
