FROM jetpackio/devbox:0.13.6

# Installing your devbox project
WORKDIR /code
USER root:root
RUN mkdir -p /code && chown ${DEVBOX_USER}:${DEVBOX_USER} /code
USER ${DEVBOX_USER}:${DEVBOX_USER}
COPY --chown=${DEVBOX_USER}:${DEVBOX_USER} devbox.json devbox.json
COPY --chown=${DEVBOX_USER}:${DEVBOX_USER} devbox.lock devbox.lock
COPY --chown=${DEVBOX_USER}:${DEVBOX_USER} Pipfile Pipfile
COPY --chown=${DEVBOX_USER}:${DEVBOX_USER} Pipfile.lock Pipfile.lock
COPY --chown=${DEVBOX_USER}:${DEVBOX_USER} app/ /code/app





RUN devbox run -- echo "Installed Packages."
RUN devbox run pipenv install
RUN devbox run fix_cffi

CMD [ "devbox", "run", "k8s"]
