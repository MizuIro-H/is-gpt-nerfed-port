FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive \
    UV_INSTALL_DIR=/usr/local/bin \
    UV_NO_MODIFY_PATH=1 \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl libegl1 libdbus-1-3 libxkbcommon-x11-0 libxcb-cursor0 \
      libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xkb1 \
    && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
RUN uv python install 3.12
COPY requirements.txt requirements-build.txt /tmp/build-requirements/
RUN uv venv --python 3.12 /opt/build-venv \
    && uv pip install --python /opt/build-venv/bin/python -r /tmp/build-requirements/requirements-build.txt
# Kept as a later layer so adding PyInstaller's objdump dependency does not
# invalidate the slow cached Python/PySide wheel installation.
RUN apt-get update && apt-get install -y --no-install-recommends binutils libglib2.0-0 libgl1 libfontconfig1 libfreetype6 libwayland-cursor0 libx11-6 libx11-xcb1 libxcb1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
