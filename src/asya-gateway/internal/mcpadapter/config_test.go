package mcpadapter_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/deliveryhero/asya/asya-gateway/internal/mcpadapter"
)

func TestRegistry_LoadFromDir(t *testing.T) {
	dir := t.TempDir()
	yamlContent := `tools:
  - name: train_model
    description: "Train a model"
    actor: start-train-flow
    timeout: 3600
    progress: true
    inputSchema:
      type: object
      properties:
        lr:
          type: number
      required: [lr]
  - name: deploy
    description: "Deploy to production"
    actor: start-deploy-flow
    timeout: 600
`
	require.NoError(t, os.WriteFile(filepath.Join(dir, "tools.yaml"), []byte(yamlContent), 0o600))

	reg := mcpadapter.NewRegistry()
	require.NoError(t, reg.LoadFromDir(dir))

	tools := reg.Tools()
	require.Len(t, tools, 2)

	assert.Equal(t, "train_model", tools[0].Name)
	assert.Equal(t, "start-train-flow", tools[0].Actor)
	assert.Equal(t, 3600, tools[0].Timeout)
	assert.True(t, tools[0].Progress)
	assert.NotEmpty(t, tools[0].InputSchema)

	assert.Equal(t, "deploy", tools[1].Name)
	assert.Equal(t, "start-deploy-flow", tools[1].Actor)
}

func TestRegistry_LoadFromDir_ValidationErrors(t *testing.T) {
	tests := []struct {
		name   string
		yaml   string
		errMsg string
	}{
		{
			name:   "missing name",
			yaml:   "tools:\n  - actor: foo\n",
			errMsg: "tool name is required",
		},
		{
			name:   "missing actor",
			yaml:   "tools:\n  - name: foo\n",
			errMsg: "actor is required",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			dir := t.TempDir()
			require.NoError(t, os.WriteFile(filepath.Join(dir, "tools.yaml"), []byte(tt.yaml), 0o600))

			reg := mcpadapter.NewRegistry()
			err := reg.LoadFromDir(dir)
			require.Error(t, err)
			assert.Contains(t, err.Error(), tt.errMsg)
		})
	}
}

func TestRegistry_GetByName(t *testing.T) {
	dir := t.TempDir()
	yamlContent := `tools:
  - name: train
    actor: start-train
    description: "Train"
  - name: deploy
    actor: start-deploy
    description: "Deploy"
`
	require.NoError(t, os.WriteFile(filepath.Join(dir, "tools.yaml"), []byte(yamlContent), 0o600))

	reg := mcpadapter.NewRegistry()
	require.NoError(t, reg.LoadFromDir(dir))

	tool := reg.GetByName("train")
	require.NotNil(t, tool)
	assert.Equal(t, "start-train", tool.Actor)

	assert.Nil(t, reg.GetByName("nonexistent"))
}

func TestRegistry_LoadFromDir_MultipleFiles(t *testing.T) {
	dir := t.TempDir()
	require.NoError(t, os.WriteFile(filepath.Join(dir, "a.yaml"), []byte("tools:\n  - name: a\n    actor: actor-a\n"), 0o600))
	require.NoError(t, os.WriteFile(filepath.Join(dir, "b.yml"), []byte("tools:\n  - name: b\n    actor: actor-b\n"), 0o600))
	require.NoError(t, os.WriteFile(filepath.Join(dir, "c.txt"), []byte("not yaml"), 0o600))

	reg := mcpadapter.NewRegistry()
	require.NoError(t, reg.LoadFromDir(dir))

	tools := reg.Tools()
	require.Len(t, tools, 2)
}

func TestRegistry_AtomicSwap(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "tools.yaml")
	require.NoError(t, os.WriteFile(path, []byte("tools:\n  - name: v1\n    actor: a1\n"), 0o600))

	reg := mcpadapter.NewRegistry()
	require.NoError(t, reg.LoadFromDir(dir))
	assert.Len(t, reg.Tools(), 1)

	// Replace with new content
	require.NoError(t, os.WriteFile(path, []byte("tools:\n  - name: v2\n    actor: a2\n  - name: v3\n    actor: a3\n"), 0o600))
	require.NoError(t, reg.LoadFromDir(dir))
	assert.Len(t, reg.Tools(), 2)
	assert.Equal(t, "v2", reg.Tools()[0].Name)
}
