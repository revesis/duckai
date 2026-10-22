#!/bin/sh
# start a virtual X server for non-headless Chrome probes
exec Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp
