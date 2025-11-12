//go:build integration

package queue

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/queue"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestSQS_NewClient(t *testing.T) {
	ctx := context.Background()
	cfg := getSQSConfig()

	client, err := queue.NewSQSClient(ctx, cfg)
	require.NoError(t, err, "Failed to create SQS client")
	require.NotNil(t, client)

	defer client.Close()
}

func TestSQS_SendEnvelope(t *testing.T) {
	ctx := context.Background()
	cfg := getSQSConfig()

	client, err := queue.NewSQSClient(ctx, cfg)
	require.NoError(t, err, "Failed to create SQS client")
	defer client.Close()

	envelope := &types.Envelope{
		ID: "test-send-1",
		Route: types.Route{
			Actors:  []string{"test-queue"},
			Current: 0,
		},
		Payload: map[string]interface{}{
			"message": "test payload",
			"value":   42,
		},
	}

	err = client.SendEnvelope(ctx, envelope)
	require.NoError(t, err, "Failed to send envelope")
}

func TestSQS_SendAndReceive(t *testing.T) {
	ctx := context.Background()
	cfg := getSQSConfig()

	client, err := queue.NewSQSClient(ctx, cfg)
	require.NoError(t, err, "Failed to create SQS client")
	defer client.Close()

	testActorName := "test-send-receive"
	testQueueName := "asya-test-send-receive"

	envelope := &types.Envelope{
		ID: "test-send-receive-1",
		Route: types.Route{
			Actors:  []string{testActorName},
			Current: 0,
		},
		Payload: map[string]interface{}{
			"data": "test message",
		},
	}

	err = client.SendEnvelope(ctx, envelope)
	require.NoError(t, err, "Failed to send envelope")

	receiveCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()

	msg, err := client.Receive(receiveCtx, testQueueName)
	require.NoError(t, err, "Failed to receive message")
	require.NotNil(t, msg)

	var received queue.ActorEnvelope
	err = json.Unmarshal(msg.Body(), &received)
	require.NoError(t, err, "Failed to unmarshal message")

	assert.Equal(t, envelope.ID, received.ID)
	assert.Equal(t, envelope.Route.Actors, received.Route.Actors)
	assert.Equal(t, envelope.Route.Current, received.Route.Current)

	err = client.Ack(ctx, msg)
	require.NoError(t, err, "Failed to ack message")
}

func TestSQS_MultipleMessages(t *testing.T) {
	ctx := context.Background()
	cfg := getSQSConfig()

	client, err := queue.NewSQSClient(ctx, cfg)
	require.NoError(t, err, "Failed to create SQS client")
	defer client.Close()

	testActorName := "test-multiple"
	testQueueName := "asya-test-multiple"

	numMessages := 5
	for i := 0; i < numMessages; i++ {
		envelope := &types.Envelope{
			ID: "test-multiple-" + string(rune('a'+i)),
			Route: types.Route{
				Actors:  []string{testActorName},
				Current: 0,
			},
			Payload: map[string]interface{}{
				"index": i,
			},
		}

		err = client.SendEnvelope(ctx, envelope)
		require.NoError(t, err, "Failed to send envelope %d", i)
	}

	receiveCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()

	receivedIDs := make(map[string]bool)

	for i := 0; i < numMessages; i++ {
		msg, err := client.Receive(receiveCtx, testQueueName)
		require.NoError(t, err, "Failed to receive message %d", i)

		var received queue.ActorEnvelope
		err = json.Unmarshal(msg.Body(), &received)
		require.NoError(t, err, "Failed to unmarshal message %d", i)

		receivedIDs[received.ID] = true

		err = client.Ack(ctx, msg)
		require.NoError(t, err, "Failed to ack message %d", i)
	}

	assert.Equal(t, numMessages, len(receivedIDs), "Should receive all messages")
}

func TestSQS_ContextCancellation(t *testing.T) {
	ctx := context.Background()
	cfg := getSQSConfig()
	cfg.WaitTimeSeconds = 5

	client, err := queue.NewSQSClient(ctx, cfg)
	require.NoError(t, err, "Failed to create SQS client")
	defer client.Close()

	receiveCtx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()

	start := time.Now()
	_, err = client.Receive(receiveCtx, "test-empty-queue")
	elapsed := time.Since(start)

	require.Error(t, err, "Expected error for cancelled context")
	assert.Less(t, elapsed, 3*time.Second, "Should respect context timeout")
}

func TestSQS_EnvelopeWithDeadline(t *testing.T) {
	ctx := context.Background()
	cfg := getSQSConfig()

	client, err := queue.NewSQSClient(ctx, cfg)
	require.NoError(t, err, "Failed to create SQS client")
	defer client.Close()

	testActorName := "test-deadline"
	testQueueName := "asya-test-deadline"

	deadline := time.Now().Add(1 * time.Hour)
	envelope := &types.Envelope{
		ID: "test-deadline-1",
		Route: types.Route{
			Actors:  []string{testActorName},
			Current: 0,
		},
		Payload: map[string]interface{}{
			"data": "test with deadline",
		},
		Deadline: deadline,
	}

	err = client.SendEnvelope(ctx, envelope)
	require.NoError(t, err, "Failed to send envelope")

	receiveCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()

	msg, err := client.Receive(receiveCtx, testQueueName)
	require.NoError(t, err, "Failed to receive message")

	var received queue.ActorEnvelope
	err = json.Unmarshal(msg.Body(), &received)
	require.NoError(t, err, "Failed to unmarshal message")

	assert.NotEmpty(t, received.Deadline, "Deadline should be set")

	receivedDeadline, err := time.Parse("2006-01-02T15:04:05Z07:00", received.Deadline)
	require.NoError(t, err, "Failed to parse deadline")

	assert.WithinDuration(t, deadline, receivedDeadline, time.Second)

	err = client.Ack(ctx, msg)
	require.NoError(t, err, "Failed to ack message")
}

func TestSQS_EmptyRoute(t *testing.T) {
	ctx := context.Background()
	cfg := getSQSConfig()

	client, err := queue.NewSQSClient(ctx, cfg)
	require.NoError(t, err, "Failed to create SQS client")
	defer client.Close()

	envelope := &types.Envelope{
		ID: "test-empty-route",
		Route: types.Route{
			Actors:  []string{},
			Current: 0,
		},
		Payload: map[string]interface{}{},
	}

	err = client.SendEnvelope(ctx, envelope)
	require.Error(t, err, "Should fail with empty route")
	assert.Contains(t, err.Error(), "no actors", "Error should mention no actors")
}

func TestSQS_LargePayload(t *testing.T) {
	ctx := context.Background()
	cfg := getSQSConfig()

	client, err := queue.NewSQSClient(ctx, cfg)
	require.NoError(t, err, "Failed to create SQS client")
	defer client.Close()

	testActorName := "test-large"
	testQueueName := "asya-test-large"

	largeData := make([]byte, 100*1024)
	for i := range largeData {
		largeData[i] = byte(i % 256)
	}

	envelope := &types.Envelope{
		ID: "test-large-1",
		Route: types.Route{
			Actors:  []string{testActorName},
			Current: 0,
		},
		Payload: map[string]interface{}{
			"large_data": largeData,
		},
	}

	err = client.SendEnvelope(ctx, envelope)
	require.NoError(t, err, "Failed to send large envelope")

	receiveCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()

	msg, err := client.Receive(receiveCtx, testQueueName)
	require.NoError(t, err, "Failed to receive large message")

	var received queue.ActorEnvelope
	err = json.Unmarshal(msg.Body(), &received)
	require.NoError(t, err, "Failed to unmarshal large message")

	assert.Equal(t, envelope.ID, received.ID)

	err = client.Ack(ctx, msg)
	require.NoError(t, err, "Failed to ack large message")
}

func TestSQS_MultipleQueues(t *testing.T) {
	ctx := context.Background()
	cfg := getSQSConfig()

	client, err := queue.NewSQSClient(ctx, cfg)
	require.NoError(t, err, "Failed to create SQS client")
	defer client.Close()

	actor1 := "test-multi-q1"
	actor2 := "test-multi-q2"
	queue1 := "asya-test-multi-q1"
	queue2 := "asya-test-multi-q2"

	envelope1 := &types.Envelope{
		ID: "test-multi-q-1",
		Route: types.Route{
			Actors:  []string{actor1},
			Current: 0,
		},
		Payload: map[string]interface{}{"queue": "q1"},
	}

	envelope2 := &types.Envelope{
		ID: "test-multi-q-2",
		Route: types.Route{
			Actors:  []string{actor2},
			Current: 0,
		},
		Payload: map[string]interface{}{"queue": "q2"},
	}

	err = client.SendEnvelope(ctx, envelope1)
	require.NoError(t, err, "Failed to send to queue1")

	err = client.SendEnvelope(ctx, envelope2)
	require.NoError(t, err, "Failed to send to queue2")

	receiveCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()

	msg1, err := client.Receive(receiveCtx, queue1)
	require.NoError(t, err, "Failed to receive from queue1")

	msg2, err := client.Receive(receiveCtx, queue2)
	require.NoError(t, err, "Failed to receive from queue2")

	var received1, received2 queue.ActorEnvelope
	json.Unmarshal(msg1.Body(), &received1)
	json.Unmarshal(msg2.Body(), &received2)

	assert.Equal(t, envelope1.ID, received1.ID)
	assert.Equal(t, envelope2.ID, received2.ID)

	client.Ack(ctx, msg1)
	client.Ack(ctx, msg2)
}
