//go:build integration

package envelopestore

import "os"

func getPostgresURL() string {
	url := os.Getenv("POSTGRES_URL")
	if url != "" {
		return url
	}
	host := os.Getenv("POSTGRES_HOST")
	if host == "" {
		host = "localhost"
	}
	return "postgres://postgres:postgres@" + host + ":5432/asya_test?sslmode=disable"
}
