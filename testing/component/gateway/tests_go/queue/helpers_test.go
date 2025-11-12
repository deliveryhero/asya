//go:build integration

package queue

import (
	"os"

	"github.com/deliveryhero/asya/asya-gateway/internal/queue"
)

func getRabbitMQURL() string {
	host := os.Getenv("RABBITMQ_HOST")
	if host == "" {
		host = "localhost"
	}
	return "amqp://guest:guest@" + host + ":5672/"
}

func getSQSConfig() queue.SQSConfig {
	endpoint := os.Getenv("ASYA_SQS_ENDPOINT")
	if endpoint == "" {
		endpoint = "http://localhost:9324"
	}

	region := os.Getenv("AWS_REGION")
	if region == "" {
		region = "us-east-1"
	}

	return queue.SQSConfig{
		Region:            region,
		Endpoint:          endpoint,
		VisibilityTimeout: 30,
		WaitTimeSeconds:   1,
	}
}
