FROM ghcr.io/prefix-dev/pixi:latest

# The base image ships an `ubuntu` user at UID/GID 1000; free them for forest3d-dev.
# Dev Containers remaps 1000 to the host UID at startup if they differ.
RUN (id -u 1000 >/dev/null 2>&1 && userdel -r $(id -nu 1000) || true) && \
    (getent group 1000 >/dev/null 2>&1 && groupdel $(getent group 1000 | cut -d: -f1) || true) && \
    groupadd -g 1000 forest3d-dev && \
    useradd -m -u 1000 -g 1000 forest3d-dev

RUN mkdir -p /workspace/forest3d && \
    chown -R forest3d-dev:forest3d-dev /workspace

USER forest3d-dev
WORKDIR /workspace/forest3d
COPY --chown=forest3d-dev:forest3d-dev pixi.toml pixi.lock pyproject.toml README.md LICENSE ./
# The editable forest3d install needs the package source to build.
COPY --chown=forest3d-dev:forest3d-dev forest3d ./forest3d
RUN pixi install --frozen
