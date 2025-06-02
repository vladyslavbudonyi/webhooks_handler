## ---------------------------------------------------------------------------------------------------
## This Makefile contains targets for work with gem-framework.
## Available targets listed below.
## ---------------------------------------------------------------------------------------------------
#  = = =   COMMON PART   = = = >

# Constants
PYTHON_MINIMAL_VER = 3.12

# App paths
CUR_PATH = $(shell pwd)
VIRTUAL_ENV ?= $(CUR_PATH)/.venv
VENV_ACTIVATE = $(VIRTUAL_ENV)/bin/activate

# Python checker
PYTHON_MINIMAL_MAIN_VER = $(shell echo $(PYTHON_MINIMAL_VER) | cut -f1 -d.)
PYTHON_MINIMAL_MAJ_VER = $(shell echo $(PYTHON_MINIMAL_VER) | cut -f2 -d.)
PYTHON_CUR_VER = $(strip $(shell python3 -V 2>&1 | grep -Po '(?<=Python )(.+)'))
PYTHON_CUR_MAIN_VER = $(shell echo $(PYTHON_CUR_VER) | cut -f1 -d.)
PYTHON_CUR_MAJ_VER = $(shell echo $(PYTHON_CUR_VER) | cut -f2 -d.)
CHECK_PYTHON_VERSION = $(shell [ $(PYTHON_CUR_MAIN_VER) -ge $(PYTHON_MINIMAL_MAIN_VER) -a $(PYTHON_CUR_MAJ_VER) -ge $(PYTHON_MINIMAL_MAJ_VER) ] && echo true)
# Docker checker
DOCKER = $(shell command -v docker)
DOCKER_COMPOSE = $(shell command -v docker-compose)
DOCKER_COMPOSE_VERSION = $(shell docker-compose --version 2>&1 | grep -Po '(\d+\.\d+\.\d+)' | cut -d'.' -f1)
USE_DOCKER_COMPOSE = $(shell [ $(DOCKER_COMPOSE_VERSION) -lt 2 ] && echo docker-compose || echo docker compose)

# Update SHELL to work via bash and PATH to work via virtual environment
SHELL =  /bin/bash

# Export PATH to work via venv
export PATH := $(VIRTUAL_ENV)/bin:$(PATH)

.PHONY: all help install run run-swt stop-swt

all: help


#  = = =   HELP TARGETS   = = = >

check-dependencies-for-run:
ifndef DOCKER
	$(error [ERROR] Docker is not available. Please install docker (https://docs.docker.com/engine/install/ubuntu/))
endif

ifndef DOCKER_COMPOSE
	$(error [ERROR] Docker-compose is not available. Please install docker-compose (https://docs.docker.com/compose/install/))
endif

# Check if venv exists
$(VENV_ACTIVATE):
ifeq ($(CHECK_PYTHON_VERSION), $(true))
	$(error [ERROR] python$(PYTHON_MINIMAL_VER) or higher expected)
endif
	python3 -m venv $(VIRTUAL_ENV)

## help                 : Show this message
help : Makefile
	@sed -n 's/^##//p' $<


#  = = =   TARGETS   = = = >
## ---------------------------------------------------------------------------------------------------
## DEVELOPMENT
##
## install              : Create .venv and install all requirements for running and development
install: $(VENV_ACTIVATE)
	cd $(CUR_PATH)
	pip install uv
	uv sync --dev

## run                  : start project in local mode
run:
ifneq ("$(wildcard $(CUR_PATH)/.env)","")
	set -a &&\
	source $(CUR_PATH)/.env &&\
	set +a &&\
	uvicorn app.main:app --host 0.0.0.0 --port 8099
else
	uvicorn app.main:app --host 0.0.0.0 --port 8099
endif

## ---------------------------------------------------------------------------------------------------


#  = = =   TARGETS   = = = >
##
## ---> docker deployment <---------------------------------------------------------------------------
## run-lsap             : start lsa perf containers
run-wh: check-dependencies-for-run
	cd $(CUR_PATH) &&\
 	$(USE_DOCKER_COMPOSE) -f docker-compose.yaml up -d --build

## stop-lsap            : stop lsa perf containers
stop-wh:
	cd $(CUR_PATH) &&\
 	$(USE_DOCKER_COMPOSE) -f docker-compose.yaml down
## ---------------------------------------------------------------------------------------------------
