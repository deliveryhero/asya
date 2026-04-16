package a2aadapter_test

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/deliveryhero/asya/asya-gateway/internal/a2aadapter"
)

func TestCardProducer_Card(t *testing.T) {
	reg := a2aadapter.NewAgentRegistry()
	reg.LoadAgentsForTest([]a2aadapter.AgentConfig{
		{
			Name:        "research",
			Description: "Research agent",
			Actor:       "start-research",
			Streaming:   true,
			Skills: []a2aadapter.SkillConfig{
				{ID: "exp", Name: "Experiment", Description: "Run exp", Tags: []string{"ml"}},
			},
			InputModes:  []string{"text/plain", "application/json"},
			OutputModes: []string{"application/json"},
		},
	})

	producer := a2aadapter.NewCardProducer(reg)
	card, err := producer.Card(context.Background())

	require.NoError(t, err)
	assert.Equal(t, "Asya Gateway", card.Name)
	assert.True(t, card.Capabilities.Streaming)
	require.Len(t, card.Skills, 1)
	assert.Equal(t, "exp", card.Skills[0].ID)
	assert.Equal(t, []string{"ml"}, card.Skills[0].Tags)
	assert.Equal(t, []string{"text/plain", "application/json"}, card.DefaultInputModes)
}

func TestCardProducer_NoSkills(t *testing.T) {
	reg := a2aadapter.NewAgentRegistry()
	reg.LoadAgentsForTest([]a2aadapter.AgentConfig{
		{Name: "simple", Description: "Simple agent", Actor: "start-simple"},
	})

	producer := a2aadapter.NewCardProducer(reg)
	card, err := producer.Card(context.Background())

	require.NoError(t, err)
	require.Len(t, card.Skills, 1)
	assert.Equal(t, "simple", card.Skills[0].ID)
}

func TestCardProducer_Empty(t *testing.T) {
	reg := a2aadapter.NewAgentRegistry()

	producer := a2aadapter.NewCardProducer(reg)
	card, err := producer.Card(context.Background())

	require.NoError(t, err)
	assert.Empty(t, card.Skills)
	assert.Equal(t, "Asya Gateway", card.Name)
}
