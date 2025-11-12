# Shared test Makefile patterns
# Include this in test Makefiles to reuse common patterns

# Common function: require environment variable
# Usage: $(call require_vars,VAR1 VAR2 VAR3)
define require_vars
	@$(foreach var,$(1),test -n "$($(var))" || (echo "[-] $(var) not defined" && exit 1);)
endef

# Common function: generate coverage filename
# Usage: $(call cov_file,mode,transport,storage)
define cov_file
$(COVERAGE_DIR)/cov$(if $(1),-$(1))$(if $(2),-$(2))$(if $(3),-$(3)).json
endef

# Common docker-compose command pattern
DOCKER_COMPOSE ?= docker compose
DOCKER_COMPOSE_UP_OPTS ?= --abort-on-container-exit --exit-code-from tester
export BUILDKIT_PROGRESS ?= plain
export COMPOSE_ANSI ?= never

# Common environment exports
export ASYA_LOG_LEVEL ?= INFO
export PYTEST_OPTS ?= -v

# Helper to clean up volumes safely
define cleanup_volumes
	docker volume ls -q | grep -E '^$(1)' | xargs -r docker volume rm 2>/dev/null || true
endef
