#!/bin/bash

echo "Downloading 4100-series index files from Astrometry.net..."

# Target directory for the index files
INDEX_DIR="$HOME/.astrometry/data"
mkdir -p "$INDEX_DIR"
cd "$INDEX_DIR" || exit 1

# Base URL for downloading
BASE_URL="http://data.astrometry.net/4100"

# 4100-series range: 4107 through 4119 (adjust as needed)
for i in $(seq -w 07 19); do
    FILE="index-41$i.fits"
    URL="$BASE_URL/$FILE"

    if [[ -f "$FILE" ]]; then
        echo "Already downloaded: $FILE"
    else
        echo "Downloading: $URL"
        curl -O "$URL"
    fi
done