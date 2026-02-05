//go:build integration

package queue

import "os"

func getRabbitMQURL() string {
	host := os.Getenv("RABBITMQ_HOST")
	if host == "" {
		host = "localhost"
	}
	return "amqp://guest:guest@" + host + ":5672/"
}
