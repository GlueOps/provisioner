FROM jetpackio/devbox:0.16.0@sha256:0475601f3ddbc1d06be7f7d4d51143dcc005400593407d5e3627fdf7edf6c7dd

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
