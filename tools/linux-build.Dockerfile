FROM ghcr.io/astral-sh/uv:latest AS uv

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
        libgstreamer-plugins-base1.0-dev \
        libgstreamer1.0-0 \
        libgstreamer1.0-dev \
        libgtk-3-0 \
        libgtk-3-dev \
        libjpeg-dev \
        libjavascriptcoregtk-4.0-18 \
        libnotify4 \
        libnotify-dev \
        libpng-dev \
        libpcre2-32-0 \
        libsdl2-2.0-0 \
        libsdl2-dev \
        libsm-dev \
        libtiff-dev \
        libvlc-dev \
        libwebkit2gtk-4.0-37 \
        libwebkit2gtk-4.0-dev \
        libxtst6 \
        libxtst-dev \
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
