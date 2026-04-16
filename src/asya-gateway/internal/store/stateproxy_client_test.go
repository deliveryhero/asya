package store

import (
	"testing"
)

// StateProxyStore is integration-tested in component tests.
// The MemoryStore tests in memory_test.go validate the MessageStore contract.

func TestStateProxyStore_ImplementsInterface(t *testing.T) {
	// Compile-time check that StateProxyStore implements MessageStore
	var _ MessageStore = (*StateProxyStore)(nil)
}

func TestMemoryStore_ImplementsInterface(t *testing.T) {
	// Compile-time check that MemoryStore implements MessageStore
	var _ MessageStore = (*MemoryStore)(nil)
}
