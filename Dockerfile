# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:0.12.0-python3.14-trixie-slim@sha256:5d7d18f8d3d16b4a3e55a8a865c150dbefb8d444c5355f7071a5457fc62352e1 AS runtime

WORKDIR /app

ENV PATH="/app/.venv/bin:${PATH}" \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 bunnyland \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin bunnyland \
    && mkdir -p /data \
    && chown 10001:10001 /data

# Install dependencies first, without the project itself, so this layer is
# cached and only rebuilt when pyproject.toml / uv.lock change.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,id=uv-cache,target=/root/.cache/uv,sharing=locked \
    uv sync --frozen --all-extras --no-dev --no-install-project

# Then add the source and install the project on top of the cached deps.
COPY README.md ./
COPY src ./src
RUN --mount=type=cache,id=uv-cache,target=/root/.cache/uv,sharing=locked \
    uv sync --frozen --all-extras --no-dev

ARG BUNNYLAND_GIT_HASH="unknown"
ENV BUNNYLAND_GIT_HASH="$BUNNYLAND_GIT_HASH"

EXPOSE 8765

USER 10001:10001

ENTRYPOINT ["bunnyland"]
CMD ["--help"]
