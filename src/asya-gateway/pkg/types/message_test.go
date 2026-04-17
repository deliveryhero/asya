package types

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestStatusAdvances_ForwardTransitions(t *testing.T) {
	assert.True(t, StatusAdvances(MessageStatusPending, MessageStatusRunning))
	assert.True(t, StatusAdvances(MessageStatusRunning, MessageStatusSucceeded))
	assert.True(t, StatusAdvances(MessageStatusRunning, MessageStatusFailed))
	assert.True(t, StatusAdvances(MessageStatusRunning, MessageStatusCanceled))
	assert.True(t, StatusAdvances(MessageStatusPaused, MessageStatusSucceeded))
	assert.True(t, StatusAdvances(MessageStatusPaused, MessageStatusFailed))
	assert.True(t, StatusAdvances(MessageStatusPending, MessageStatusSucceeded))
}

func TestStatusAdvances_BackwardTransitionsRejected(t *testing.T) {
	assert.False(t, StatusAdvances(MessageStatusRunning, MessageStatusPending))
	assert.False(t, StatusAdvances(MessageStatusSucceeded, MessageStatusRunning))
	assert.False(t, StatusAdvances(MessageStatusFailed, MessageStatusPending))
	assert.False(t, StatusAdvances(MessageStatusCanceled, MessageStatusRunning))
}

func TestStatusAdvances_SameLevelRejected(t *testing.T) {
	assert.False(t, StatusAdvances(MessageStatusSucceeded, MessageStatusFailed))
	assert.False(t, StatusAdvances(MessageStatusFailed, MessageStatusSucceeded))
	assert.False(t, StatusAdvances(MessageStatusRunning, MessageStatusRunning))
	assert.False(t, StatusAdvances(MessageStatusPending, MessageStatusPending))
}

func TestIsTerminal(t *testing.T) {
	assert.True(t, MessageStatusSucceeded.IsTerminal())
	assert.True(t, MessageStatusFailed.IsTerminal())
	assert.True(t, MessageStatusCanceled.IsTerminal())
	assert.False(t, MessageStatusRunning.IsTerminal())
	assert.False(t, MessageStatusPending.IsTerminal())
	assert.False(t, MessageStatusPaused.IsTerminal())
}
