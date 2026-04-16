package a2aadapter_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/deliveryhero/asya/asya-gateway/internal/a2aadapter"
)

func TestAgentRegistry_LoadFromDir(t *testing.T) {
	dir := t.TempDir()
	yamlContent := `agents:
  - name: autoresearch
    description: "Research agent"
    actor: start-autoresearch
    timeout: 14400
    streaming: true
    skills:
      - id: experiment
        name: Run experiment
        description: "Execute experiments"
        tags: [ml, training]
    inputModes: [text/plain, application/json]
    outputModes: [text/plain, application/json]
`
	require.NoError(t, os.WriteFile(filepath.Join(dir, "agents.yaml"), []byte(yamlContent), 0o600))

	reg := a2aadapter.NewAgentRegistry()
	require.NoError(t, reg.LoadFromDir(dir))

	agents := reg.Agents()
	require.Len(t, agents, 1)
	assert.Equal(t, "autoresearch", agents[0].Name)
	assert.Equal(t, "start-autoresearch", agents[0].Actor)
	assert.Equal(t, 14400, agents[0].Timeout)
	assert.True(t, agents[0].Streaming)
	require.Len(t, agents[0].Skills, 1)
	assert.Equal(t, "experiment", agents[0].Skills[0].ID)
	assert.Equal(t, []string{"ml", "training"}, agents[0].Skills[0].Tags)
}

func TestAgentRegistry_ValidationErrors(t *testing.T) {
	tests := []struct {
		name   string
		yaml   string
		errMsg string
	}{
		{
			name:   "missing name",
			yaml:   "agents:\n  - actor: foo\n",
			errMsg: "agent name is required",
		},
		{
			name:   "missing actor",
			yaml:   "agents:\n  - name: foo\n",
			errMsg: "actor is required",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			dir := t.TempDir()
			require.NoError(t, os.WriteFile(filepath.Join(dir, "agents.yaml"), []byte(tt.yaml), 0o600))

			reg := a2aadapter.NewAgentRegistry()
			err := reg.LoadFromDir(dir)
			require.Error(t, err)
			assert.Contains(t, err.Error(), tt.errMsg)
		})
	}
}

func TestAgentRegistry_ResolveActor(t *testing.T) {
	reg := a2aadapter.NewAgentRegistry()
	reg.LoadAgentsForTest([]a2aadapter.AgentConfig{
		{
			Name:  "research",
			Actor: "start-research",
			Skills: []a2aadapter.SkillConfig{
				{ID: "experiment", Name: "Run experiment"},
			},
		},
		{
			Name:  "deploy",
			Actor: "start-deploy",
			Skills: []a2aadapter.SkillConfig{
				{ID: "rollout", Name: "Rollout"},
			},
		},
	})

	agent, err := reg.ResolveActor("experiment")
	require.NoError(t, err)
	assert.Equal(t, "start-research", agent.Actor)

	agent, err = reg.ResolveActor("rollout")
	require.NoError(t, err)
	assert.Equal(t, "start-deploy", agent.Actor)

	_, err = reg.ResolveActor("unknown")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "not found")

	_, err = reg.ResolveActor("")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "skill not specified")
}

func TestAgentRegistry_ResolveActor_SingleAgent(t *testing.T) {
	reg := a2aadapter.NewAgentRegistry()
	reg.LoadAgentsForTest([]a2aadapter.AgentConfig{
		{Name: "solo", Actor: "start-solo"},
	})

	agent, err := reg.ResolveActor("")
	require.NoError(t, err)
	assert.Equal(t, "start-solo", agent.Actor)
}

func TestAgentRegistry_ResolveActor_Empty(t *testing.T) {
	reg := a2aadapter.NewAgentRegistry()
	_, err := reg.ResolveActor("")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "no A2A agents registered")
}
