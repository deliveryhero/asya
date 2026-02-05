//go:build integration

package envelopestore

import (
	"context"
	"database/sql"
	"os"

	_ "github.com/jackc/pgx/v5/stdlib"
)

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

func truncateTestTables(ctx context.Context) error {
	db, err := sql.Open("pgx", getPostgresURL())
	if err != nil {
		return err
	}
	defer db.Close()

	_, err = db.ExecContext(ctx, "TRUNCATE TABLE envelope_updates, envelopes CASCADE")
	return err
}
