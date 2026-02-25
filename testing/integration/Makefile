.PHONY: test cov clean
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

test:
	@$(MAKE) -C sidecar test
	@$(MAKE) -C gateway test
	@$(MAKE) -C sidecar-runtime test
	@$(MAKE) -C gateway-actors test
	@$(MAKE) -C stateful-actors test
	@$(MAKE) -C fan-in test
	@echo "[+] All integration tests succeeded."

cov:
	@$(MAKE) -C sidecar cov
	@$(MAKE) -C gateway cov
	@$(MAKE) -C sidecar-runtime cov
	@$(MAKE) -C gateway-actors cov
	@$(MAKE) -C stateful-actors cov
	@$(MAKE) -C fan-in cov

clean:
	@$(MAKE) -C sidecar clean
	@$(MAKE) -C gateway clean
	@$(MAKE) -C sidecar-runtime clean
	@$(MAKE) -C gateway-actors clean
	@$(MAKE) -C stateful-actors clean
	@$(MAKE) -C fan-in clean
