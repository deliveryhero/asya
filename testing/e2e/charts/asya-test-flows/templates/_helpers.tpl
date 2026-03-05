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
Pub/Sub spec fields (gcpProject). Include in AsyncActor spec when transport is pubsub.
*/}}
{{- define "asya-test-flows.pubsub-spec" -}}
{{- if and (eq .Values.transport "pubsub") .Values.gcpProject }}
gcpProject: {{ .Values.gcpProject }}
{{- end }}
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
- name: ASYA_HANDLER_ROUTER_TEST_NESTED_FLOW_LINE_4_IF
  value: asya_testing.flows.nested_if.compiled.routers.router_test_nested_flow_line_4_if
- name: ASYA_HANDLER_ROUTER_TEST_NESTED_FLOW_LINE_6_IF
  value: asya_testing.flows.nested_if.compiled.routers.router_test_nested_flow_line_6_if
- name: ASYA_HANDLER_ROUTER_TEST_NESTED_FLOW_LINE_7_SEQ
  value: asya_testing.flows.nested_if.compiled.routers.router_test_nested_flow_line_7_seq
- name: ASYA_HANDLER_ROUTER_TEST_NESTED_FLOW_LINE_10_SEQ
  value: asya_testing.flows.nested_if.compiled.routers.router_test_nested_flow_line_10_seq
- name: ASYA_HANDLER_ROUTER_TEST_NESTED_FLOW_LINE_14_IF
  value: asya_testing.flows.nested_if.compiled.routers.router_test_nested_flow_line_14_if
- name: ASYA_HANDLER_ROUTER_TEST_NESTED_FLOW_LINE_15_SEQ
  value: asya_testing.flows.nested_if.compiled.routers.router_test_nested_flow_line_15_seq
- name: ASYA_HANDLER_ROUTER_TEST_NESTED_FLOW_LINE_18_SEQ
  value: asya_testing.flows.nested_if.compiled.routers.router_test_nested_flow_line_18_seq
- name: ASYA_HANDLER_END_TEST_NESTED_FLOW
  value: asya_testing.flows.nested_if.compiled.routers.end_test_nested_flow
{{- end }}

{{/*
Flow handler resolution environment variables for research-flow (fan-out/fan-in).
These env vars allow routers to resolve handler names to actor queue names.

Handler-to-actor name mapping (via ASYA_HANDLER_<ACTOR_NAME_UPPER> env vars):
  ASYA_HANDLER_START_RESEARCH_FLOW      -> actor "start-research-flow"
  ASYA_HANDLER_FANOUT_RESEARCH_FLOW_L2  -> actor "fanout-research-flow-l2"
  ASYA_HANDLER_END_RESEARCH_FLOW        -> actor "end-research-flow"
  ASYA_HANDLER_RESEARCH_AGENT           -> actor "research-agent"
  ASYA_HANDLER_RESEARCH_FLOW_AGGREGATOR -> actor "research-flow-aggregator"
  ASYA_HANDLER_RESEARCH_FLOW_SUMMARIZER -> actor "research-flow-summarizer"

resolve("fanin_research_flow_line_2") -> "research-flow-aggregator"
  (fan-in destination: crew split_key aggregator)
resolve("summarizer") -> "research-flow-summarizer"
  (post-aggregation handler from flow.py)
*/}}
{{- define "asya-test-flows.research-flow-handler-env" -}}
- name: ASYA_HANDLER_START_RESEARCH_FLOW
  value: asya_testing.flows.research_flow.compiled.routers.start_research_flow
- name: ASYA_HANDLER_FANOUT_RESEARCH_FLOW_L2
  value: asya_testing.flows.research_flow.compiled.routers.fanout_research_flow_line_2
- name: ASYA_HANDLER_END_RESEARCH_FLOW
  value: asya_testing.flows.research_flow.compiled.routers.end_research_flow
- name: ASYA_HANDLER_RESEARCH_AGENT
  value: asya_testing.flows.research_flow.flow.research_agent
- name: ASYA_HANDLER_RESEARCH_FLOW_AGGREGATOR
  value: asya_testing.flows.research_flow.compiled.routers.fanin_research_flow_line_2
- name: ASYA_HANDLER_RESEARCH_FLOW_SUMMARIZER
  value: asya_testing.flows.research_flow.flow.summarizer
{{- end }}
