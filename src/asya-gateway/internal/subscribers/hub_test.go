package subscribers

import (
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestHub_SubscribeAndPublish(t *testing.T) {
	hub := New()
	ch := hub.Subscribe("msg-1")
	hub.Publish("msg-1", types.Event{Type: "status", Status: types.MessageStatusRunning})

	select {
	case event := <-ch:
		assert.Equal(t, "status", event.Type)
		assert.Equal(t, types.MessageStatusRunning, event.Status)
	case <-time.After(time.Second):
		t.Fatal("timed out waiting for event")
	}
}

func TestHub_Unsubscribe(t *testing.T) {
	hub := New()
	ch := hub.Subscribe("msg-1")
	hub.Unsubscribe("msg-1", ch)

	// Verify channel is closed
	_, ok := <-ch
	assert.False(t, ok)
}

func TestHub_PublishToMultipleSubscribers(t *testing.T) {
	hub := New()
	ch1 := hub.Subscribe("msg-1")
	ch2 := hub.Subscribe("msg-1")

	event := types.Event{Type: "fly", Data: []byte(`{"text":"hello"}`)}
	hub.Publish("msg-1", event)

	for _, ch := range []<-chan types.Event{ch1, ch2} {
		select {
		case got := <-ch:
			assert.Equal(t, "fly", got.Type)
		case <-time.After(time.Second):
			t.Fatal("timed out")
		}
	}
}

func TestHub_PublishNoSubscribers(t *testing.T) {
	hub := New()
	// Should not panic
	hub.Publish("msg-nonexistent", types.Event{Type: "status"})
}

func TestHub_DropOnFullChannel(t *testing.T) {
	hub := New()
	ch := hub.Subscribe("msg-1")

	// Fill the channel
	for i := 0; i < channelBuffer; i++ {
		hub.Publish("msg-1", types.Event{Type: "fly"})
	}

	// This should be dropped (channel full) but not block
	hub.Publish("msg-1", types.Event{Type: "fly"})

	// Drain and verify we got exactly channelBuffer events
	count := 0
	for {
		select {
		case <-ch:
			count++
		default:
			goto done
		}
	}
done:
	assert.Equal(t, channelBuffer, count)
}

func TestHub_UnsubscribeCleansUp(t *testing.T) {
	hub := New()
	ch1 := hub.Subscribe("msg-1")
	ch2 := hub.Subscribe("msg-1")

	hub.Unsubscribe("msg-1", ch1)

	// ch2 should still receive events
	hub.Publish("msg-1", types.Event{Type: "status"})
	select {
	case <-ch2:
		// ok
	case <-time.After(time.Second):
		t.Fatal("ch2 should still receive events")
	}

	hub.Unsubscribe("msg-1", ch2)

	// After unsubscribing both, the map entry should be cleaned up
	hub.mu.RLock()
	_, exists := hub.subs["msg-1"]
	hub.mu.RUnlock()
	require.False(t, exists)
}
