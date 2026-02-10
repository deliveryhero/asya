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
