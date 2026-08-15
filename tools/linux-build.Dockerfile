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
        libnotify4 \
        libsdl2-2.0-0 \
        libvlc-dev \
        python3 \
        python3-dev \
        python3-pip \
        python3-venv \
        tar \
        unzip \
        vlc \
    && rm -rf /var/lib/apt/lists/*

ENV PIP_FIND_LINKS=https://extras.wxpython.org/wxPython4/extras/linux/gtk3/ubuntu-22.04

WORKDIR /src
