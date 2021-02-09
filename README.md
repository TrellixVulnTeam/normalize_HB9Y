# Normalize micro-service

[![Build Status](https://ci.dev-1.opertusmundi.eu:9443/api/badges/OpertusMundi/normalize/status.svg?ref=refs/heads/main)](https://ci.dev-1.opertusmundi.eu:9443/OpertusMundi/normalize)

## Build and run as a container

Copy `.env.example` to `.env` and configure if needed (e.g `FLASK_ENV` variable).

Copy `compose.yml.example` to `compose.yml` (or `docker-compose.yml`) and adjust to your needs (e.g. specify volume source locations etc.). You will at least need to configure the network (inside `compose.yml`) to attach to. 

For example, you can create a private network named `opertusmundi_network`:

    docker network create --attachable opertusmundi_network

Build:

    docker-compose -f compose.yml build

Prepare the following files/directories:

   * `./data/normalize.sqlite`:  the SQLite database (an empty database, if running for first time)
   * `./data/secret_key`: file needed for signing/encrypting session data (can be generated with `openssl rand`)
   * `./logs`: a directory to keep logs under
   * `./output`: a directory to be used as root of a hierarchy of output files
   * `./temp`: a directory for temporary data

Start application:
    
    docker-compose -f compose.yml up -d


## Run tests

Copy `compose-testing.yml.example` to `compose-testing.yml` and adjust to your needs. This is a just a docker-compose recipe for setting up the testing container.

Build image for testing:

    docker-compose -f compose-testing.yml build

Run nosetests (in an ephemeral container):

    docker-compose -f compose-testing.yml run --rm --user "$(id -u):$(id -g)" nosetests -v


