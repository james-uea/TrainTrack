# postgis/postgis publishes no arm64 images, so add PostGIS to the official Postgres image from the
# PGDG apt repository it already uses. Keep the major version in step with the data volume.
FROM postgres:18

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-18-postgis-3 \
    && rm -rf /var/lib/apt/lists/*
