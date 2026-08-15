FROM ghcr.io/astral-sh/uv:0.11.6 AS uv

FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        ffmpeg \
        git \
        libgstreamer-plugins-base1.0-0 \
        libgstreamer1.0-0 \
        libgtk-3-0 \
        libjavascriptcoregtk-4.0-18 \
        libnotify4 \
        libpcre2-32-0 \
        libsdl2-2.0-0 \
        libvlc-dev \
        libwebkit2gtk-4.0-37 \
        libxtst6 \
        python3 \
        python3-dev \
        python3-pip \
        python3-venv \
        tar \
        unzip \
        vlc \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /usr/local/bin/

WORKDIR /src
