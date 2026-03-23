{{/*
Expand the name of the chart.
*/}}
{{- define "asya-test-flows.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "asya-test-flows.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
Labels for AsyncActor CRs should NOT include reserved prefixes (app.kubernetes.io/, etc.)
as these are managed by the operator and added to child resources.
*/}}
{{- define "asya-test-flows.labels" -}}
helm.sh/chart: {{ include "asya-test-flows.chart" . }}
asya.sh/test-type: flow
{{- end }}

{{/*
Flow handler resolution environment variables for nested-if flow.
These environment variables allow routers to resolve handler names to actor names.
*/}}
{{- define "asya-test-flows.nested-if-handler-env" -}}
- name: ASYA_HANDLER_VALIDATE_INPUT
  value: asya_testing.flows.nested_if.flow.validate_input
- name: ASYA_HANDLER_ROUTE_A_X
  value: asya_testing.flows.nested_if.flow.route_a_x
- name: ASYA_HANDLER_ROUTE_A_Y
  value: asya_testing.flows.nested_if.flow.route_a_y
- name: ASYA_HANDLER_ROUTE_B_X
  value: asya_testing.flows.nested_if.flow.route_b_x
- name: ASYA_HANDLER_ROUTE_B_Y
  value: asya_testing.flows.nested_if.flow.route_b_y
- name: ASYA_HANDLER_FINALIZE_RESULT
  value: asya_testing.flows.nested_if.flow.finalize_result
- name: ASYA_HANDLER_ROUTER_TEST_NESTED_FLOW_IF_LEVEL1_EQ_A
  value: asya_testing.flows.nested_if.compiled.routers.router_test_nested_flow_if_level1_eq_a
- name: ASYA_HANDLER_ROUTER_TEST_NESTED_FLOW_IF_LEVEL2_EQ_X
  value: asya_testing.flows.nested_if.compiled.routers.router_test_nested_flow_if_level2_eq_x
- name: ASYA_HANDLER_ROUTER_TEST_NESTED_FLOW_SEQ_SET_ROUTE
  value: asya_testing.flows.nested_if.compiled.routers.router_test_nested_flow_seq_set_route
- name: ASYA_HANDLER_ROUTER_TEST_NESTED_FLOW_SEQ_SET_ROUTE_2
  value: asya_testing.flows.nested_if.compiled.routers.router_test_nested_flow_seq_set_route_2
- name: ASYA_HANDLER_ROUTER_TEST_NESTED_FLOW_IF_LEVEL2_EQ_X_2
  value: asya_testing.flows.nested_if.compiled.routers.router_test_nested_flow_if_level2_eq_x_2
- name: ASYA_HANDLER_ROUTER_TEST_NESTED_FLOW_SEQ_SET_ROUTE_3
  value: asya_testing.flows.nested_if.compiled.routers.router_test_nested_flow_seq_set_route_3
- name: ASYA_HANDLER_ROUTER_TEST_NESTED_FLOW_SEQ_SET_ROUTE_4
  value: asya_testing.flows.nested_if.compiled.routers.router_test_nested_flow_seq_set_route_4
{{- end }}

{{/*
Flow handler resolution environment variables for research-flow (fan-out/fan-in).
These env vars allow routers to resolve handler names to actor queue names.

Handler-to-actor name mapping (via ASYA_HANDLER_<ACTOR_NAME_UPPER> env vars):
  ASYA_HANDLER_START_RESEARCH_FLOW      -> actor "start-research-flow"
  ASYA_HANDLER_ROUTER_RESEARCH_FLOW_FANOUT_RESULTS -> actor "router-research-flow-fanout-results"
  ASYA_HANDLER_END_RESEARCH_FLOW        -> actor "end-research-flow"
  ASYA_HANDLER_RESEARCH_AGENT           -> actor "research-agent"
  ASYA_HANDLER_RESEARCH_FLOW_AGGREGATOR -> actor "research-flow-aggregator"
  ASYA_HANDLER_RESEARCH_FLOW_SUMMARIZER -> actor "research-flow-summarizer"

resolve("fanin_research_flow_results") -> "research-flow-aggregator"
  (fan-in destination: crew split_key aggregator)
resolve("summarizer") -> "research-flow-summarizer"
  (post-aggregation handler from flow.py)
*/}}
{{- define "asya-test-flows.research-flow-handler-env" -}}
- name: ASYA_HANDLER_START_RESEARCH_FLOW
  value: asya_testing.flows.research_flow.compiled.routers.start_research_flow
- name: ASYA_HANDLER_ROUTER_RESEARCH_FLOW_FANOUT_RESULTS
  value: asya_testing.flows.research_flow.compiled.routers.router_research_flow_fanout_results
- name: ASYA_HANDLER_END_RESEARCH_FLOW
  value: asya_testing.flows.research_flow.compiled.routers.end_research_flow
- name: ASYA_HANDLER_RESEARCH_AGENT
  value: asya_testing.flows.research_flow.flow.research_agent
- name: ASYA_HANDLER_RESEARCH_FLOW_AGGREGATOR
  value: asya_testing.flows.research_flow.compiled.routers.fanin_research_flow_results
- name: ASYA_HANDLER_RESEARCH_FLOW_SUMMARIZER
  value: asya_testing.flows.research_flow.flow.summarizer
{{- end }}
