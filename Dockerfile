# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:python3.12-bookworm AS runtime

WORKDIR /app

ENV PATH="/app/.venv/bin:${PATH}" \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

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

ENTRYPOINT ["bunnyland"]
CMD ["--help"]
