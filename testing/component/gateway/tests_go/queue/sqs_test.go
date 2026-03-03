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

func TestSQS_SendMessage(t *testing.T) {
	ctx := context.Background()
	cfg := getSQSConfig()

	client, err := queue.NewSQSClient(ctx, cfg)
	require.NoError(t, err, "Failed to create SQS client")
	defer client.Close()

	task := &types.Task{
		ID: "test-send-1",
		Route: types.Route{
			Prev: []string{},
			Curr: "test-queue",
			Next: []string{},
		},
		Payload: map[string]interface{}{
			"message": "test payload",
			"value":   42,
		},
	}

	err = client.SendMessage(ctx, task)
	require.NoError(t, err, "Failed to send message")
}

func TestSQS_SendAndReceive(t *testing.T) {
	ctx := context.Background()
	cfg := getSQSConfig()

	client, err := queue.NewSQSClient(ctx, cfg)
	require.NoError(t, err, "Failed to create SQS client")
	defer client.Close()

	testActorName := "test-send-receive"
	testQueueName := "asya-default-test-send-receive"

	task := &types.Task{
		ID: "test-send-receive-1",
		Route: types.Route{
			Prev: []string{},
			Curr: testActorName,
			Next: []string{},
		},
		Payload: map[string]interface{}{
			"data": "test message",
		},
	}

	err = client.SendMessage(ctx, task)
	require.NoError(t, err, "Failed to send message")

	receiveCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()

	msg, err := client.Receive(receiveCtx, testQueueName)
	require.NoError(t, err, "Failed to receive message")
	require.NotNil(t, msg)

	var received queue.ActorEnvelope
	err = json.Unmarshal(msg.Body(), &received)
	require.NoError(t, err, "Failed to unmarshal message")

	assert.Equal(t, task.ID, received.ID)
	assert.Equal(t, task.Route.Curr, received.Route.Curr)
	assert.Equal(t, task.Route.Prev, received.Route.Prev)
	assert.Equal(t, task.Route.Next, received.Route.Next)

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
	testQueueName := "asya-default-test-multiple"

	numMessages := 5
	for i := 0; i < numMessages; i++ {
		task := &types.Task{
			ID: "test-multiple-" + string(rune('a'+i)),
			Route: types.Route{
				Prev: []string{},
				Curr: testActorName,
				Next: []string{},
			},
			Payload: map[string]interface{}{
				"index": i,
			},
		}

		err = client.SendMessage(ctx, task)
		require.NoError(t, err, "Failed to send message %d", i)
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

func TestSQS_TaskWithDeadline(t *testing.T) {
	ctx := context.Background()
	cfg := getSQSConfig()

	client, err := queue.NewSQSClient(ctx, cfg)
	require.NoError(t, err, "Failed to create SQS client")
	defer client.Close()

	testActorName := "test-deadline"
	testQueueName := "asya-default-test-deadline"

	deadline := time.Now().Add(1 * time.Hour)
	task := &types.Task{
		ID: "test-deadline-1",
		Route: types.Route{
			Prev: []string{},
			Curr: testActorName,
			Next: []string{},
		},
		Payload: map[string]interface{}{
			"data": "test with deadline",
		},
		Deadline: deadline,
	}

	err = client.SendMessage(ctx, task)
	require.NoError(t, err, "Failed to send message")

	receiveCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()

	msg, err := client.Receive(receiveCtx, testQueueName)
	require.NoError(t, err, "Failed to receive message")

	var received queue.ActorEnvelope
	err = json.Unmarshal(msg.Body(), &received)
	require.NoError(t, err, "Failed to unmarshal message")

	require.NotNil(t, received.Status, "Status should be set")
	assert.NotEmpty(t, received.Status.DeadlineAt, "Status.DeadlineAt should be set")

	receivedDeadline, err := time.Parse(time.RFC3339, received.Status.DeadlineAt)
	require.NoError(t, err, "Failed to parse deadline_at")

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

	task := &types.Task{
		ID: "test-empty-route",
		Route: types.Route{
			Prev: []string{},
			Curr: "", // Empty curr to trigger empty route error
			Next: []string{},
		},
		Payload: map[string]interface{}{},
	}

	err = client.SendMessage(ctx, task)
	require.Error(t, err, "Should fail with empty route")
	assert.Contains(t, err.Error(), "no current actor", "Error should mention no current actor")
}

func TestSQS_LargePayload(t *testing.T) {
	ctx := context.Background()
	cfg := getSQSConfig()

	client, err := queue.NewSQSClient(ctx, cfg)
	require.NoError(t, err, "Failed to create SQS client")
	defer client.Close()

	testActorName := "test-large"
	testQueueName := "asya-default-test-large"

	largeData := make([]byte, 100*1024)
	for i := range largeData {
		largeData[i] = byte(i % 256)
	}

	task := &types.Task{
		ID: "test-large-1",
		Route: types.Route{
			Prev: []string{},
			Curr: testActorName,
			Next: []string{},
		},
		Payload: map[string]interface{}{
			"large_data": largeData,
		},
	}

	err = client.SendMessage(ctx, task)
	require.NoError(t, err, "Failed to send large message")

	receiveCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()

	msg, err := client.Receive(receiveCtx, testQueueName)
	require.NoError(t, err, "Failed to receive large message")

	var received queue.ActorEnvelope
	err = json.Unmarshal(msg.Body(), &received)
	require.NoError(t, err, "Failed to unmarshal large message")

	assert.Equal(t, task.ID, received.ID)

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
	queue1 := "asya-default-test-multi-q1"
	queue2 := "asya-default-test-multi-q2"

	task1 := &types.Task{
		ID: "test-multi-q-1",
		Route: types.Route{
			Prev: []string{},
			Curr: actor1,
			Next: []string{},
		},
		Payload: map[string]interface{}{"queue": "q1"},
	}

	task2 := &types.Task{
		ID: "test-multi-q-2",
		Route: types.Route{
			Prev: []string{},
			Curr: actor2,
			Next: []string{},
		},
		Payload: map[string]interface{}{"queue": "q2"},
	}

	err = client.SendMessage(ctx, task1)
	require.NoError(t, err, "Failed to send to queue1")

	err = client.SendMessage(ctx, task2)
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

	assert.Equal(t, task1.ID, received1.ID)
	assert.Equal(t, task2.ID, received2.ID)

	client.Ack(ctx, msg1)
	client.Ack(ctx, msg2)
}
