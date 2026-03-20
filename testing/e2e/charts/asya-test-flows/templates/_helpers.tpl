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
- name: ASYA_HANDLER_ROUTER_TEST_NESTED_FLOW_LINE_9_IF_7
  value: asya_testing.flows.nested_if.compiled.routers.router_test_nested_flow_line_9_if_7
- name: ASYA_HANDLER_ROUTER_TEST_NESTED_FLOW_LINE_11_IF_3
  value: asya_testing.flows.nested_if.compiled.routers.router_test_nested_flow_line_11_if_3
- name: ASYA_HANDLER_ROUTER_TEST_NESTED_FLOW_LINE_12_SEQ_1
  value: asya_testing.flows.nested_if.compiled.routers.router_test_nested_flow_line_12_seq_1
- name: ASYA_HANDLER_ROUTER_TEST_NESTED_FLOW_LINE_15_SEQ_2
  value: asya_testing.flows.nested_if.compiled.routers.router_test_nested_flow_line_15_seq_2
- name: ASYA_HANDLER_ROUTER_TEST_NESTED_FLOW_LINE_19_IF_6
  value: asya_testing.flows.nested_if.compiled.routers.router_test_nested_flow_line_19_if_6
- name: ASYA_HANDLER_ROUTER_TEST_NESTED_FLOW_LINE_20_SEQ_4
  value: asya_testing.flows.nested_if.compiled.routers.router_test_nested_flow_line_20_seq_4
- name: ASYA_HANDLER_ROUTER_TEST_NESTED_FLOW_LINE_23_SEQ_5
  value: asya_testing.flows.nested_if.compiled.routers.router_test_nested_flow_line_23_seq_5
{{- end }}

{{/*
Flow handler resolution environment variables for research-flow (fan-out/fan-in).
These env vars allow routers to resolve handler names to actor queue names.

Handler-to-actor name mapping (via ASYA_HANDLER_<ACTOR_NAME_UPPER> env vars):
  ASYA_HANDLER_START_RESEARCH_FLOW      -> actor "start-research-flow"
  ASYA_HANDLER_ROUTER_RESEARCH_FLOW_LINE_7_FANOUT_1 -> actor "router-research-flow-line-7-fanout-1"
  ASYA_HANDLER_END_RESEARCH_FLOW        -> actor "end-research-flow"
  ASYA_HANDLER_RESEARCH_AGENT           -> actor "research-agent"
  ASYA_HANDLER_RESEARCH_FLOW_AGGREGATOR -> actor "research-flow-aggregator"
  ASYA_HANDLER_RESEARCH_FLOW_SUMMARIZER -> actor "research-flow-summarizer"

resolve("fanin_research_flow_line_7") -> "research-flow-aggregator"
  (fan-in destination: crew split_key aggregator)
resolve("summarizer") -> "research-flow-summarizer"
  (post-aggregation handler from flow.py)
*/}}
{{- define "asya-test-flows.research-flow-handler-env" -}}
- name: ASYA_HANDLER_START_RESEARCH_FLOW
  value: asya_testing.flows.research_flow.compiled.routers.start_research_flow
- name: ASYA_HANDLER_ROUTER_RESEARCH_FLOW_LINE_7_FANOUT_1
  value: asya_testing.flows.research_flow.compiled.routers.router_research_flow_line_7_fanout_1
- name: ASYA_HANDLER_END_RESEARCH_FLOW
  value: asya_testing.flows.research_flow.compiled.routers.end_research_flow
- name: ASYA_HANDLER_RESEARCH_AGENT
  value: asya_testing.flows.research_flow.flow.research_agent
- name: ASYA_HANDLER_RESEARCH_FLOW_AGGREGATOR
  value: asya_testing.flows.research_flow.compiled.routers.fanin_research_flow_line_7
- name: ASYA_HANDLER_RESEARCH_FLOW_SUMMARIZER
  value: asya_testing.flows.research_flow.flow.summarizer
{{- end }}
