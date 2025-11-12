.PHONY: test cov clean
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

test:
	@$(MAKE) -C sidecar test
	@$(MAKE) -C gateway test
	@$(MAKE) -C sidecar-runtime test
	@$(MAKE) -C gateway-actors test
	@$(MAKE) -C operator test
	@echo "[+] All integration tests succeeded."

cov:
	@$(MAKE) -C sidecar cov
	@$(MAKE) -C gateway cov
	@$(MAKE) -C sidecar-runtime cov
	@$(MAKE) -C gateway-actors cov
	@$(MAKE) -C operator cov

clean:
	@$(MAKE) -C sidecar clean
	@$(MAKE) -C gateway clean
	@$(MAKE) -C sidecar-runtime clean
	@$(MAKE) -C gateway-actors clean
	@$(MAKE) -C operator clean
