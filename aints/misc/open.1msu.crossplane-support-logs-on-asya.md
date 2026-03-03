---
title: Support kubectl logs asya/actor-name
priority: 2 # medium
---

Support asyncactor resource for logs - exactly same behavior as for deployment but resolving it via label `asya.sh/actor`.

```
kubectl logs asya/actor-name  # automatically: -c asya-runtime
kubectl logs asya/actor-name -C asya-sidecar
kubectl logs asya/actor-name -f  # attach

19:51 $ k -n asya-e2e logs --help
Print the logs for a container in a pod or specified resource. If the pod has only one container, the container name is
optional.

Examples:
  # Return snapshot logs from pod nginx with only one container
  kubectl logs nginx
  
  # Return snapshot logs from pod nginx, prefixing each line with the source pod and container name
  kubectl logs nginx --prefix
  
  # Return snapshot logs from pod nginx, limiting output to 500 bytes
  kubectl logs nginx --limit-bytes=500
  
  # Return snapshot logs from pod nginx, waiting up to 20 seconds for it to start running.
  kubectl logs nginx --pod-running-timeout=20s
  
  # Return snapshot logs from pod nginx with multi containers
  kubectl logs nginx --all-containers=true
  
  # Return snapshot logs from all pods in the deployment nginx
  kubectl logs deployment/nginx --all-pods=true
  
  # Return snapshot logs from all containers in pods defined by label app=nginx
  kubectl logs -l app=nginx --all-containers=true
  
  # Return snapshot logs from all pods defined by label app=nginx, limiting concurrent log requests to 10 pods
  kubectl logs -l app=nginx --max-log-requests=10
  
  # Return snapshot of previous terminated ruby container logs from pod web-1
  kubectl logs -p -c ruby web-1
  
  # Begin streaming the logs from pod nginx, continuing even if errors occur
  kubectl logs nginx -f --ignore-errors=true
  
  # Begin streaming the logs of the ruby container in pod web-1
  kubectl logs -f -c ruby web-1
  
  # Begin streaming the logs from all containers in pods defined by label app=nginx
  kubectl logs -f -l app=nginx --all-containers=true
  
  # Display only the most recent 20 lines of output in pod nginx
  kubectl logs --tail=20 nginx
  
  # Show all logs from pod nginx written in the last hour
  kubectl logs --since=1h nginx
  
  # Show all logs with timestamps from pod nginx starting from August 30, 2024, at 06:00:00 UTC
  kubectl logs nginx --since-time=2024-08-30T06:00:00Z --timestamps=true
  
  # Show logs from a kubelet with an expired serving certificate
  kubectl logs --insecure-skip-tls-verify-backend nginx
  
  # Return snapshot logs from first container of a job named hello
  kubectl logs job/hello
  
  # Return snapshot logs from container nginx-1 of a deployment named nginx
  kubectl logs deployment/nginx -c nginx-1

Options:
    --all-containers=false:
        Get all containers' logs in the pod(s).

    --all-pods=false:
        Get logs from all pod(s). Sets prefix to true.

    -c, --container='':
        Print the logs of this container

    -f, --follow=false:
        Specify if the logs should be streamed.

    --ignore-errors=false:
        If watching / following pod logs, allow for any errors that occur to be non-fatal

    --insecure-skip-tls-verify-backend=false:
        Skip verifying the identity of the kubelet that logs are requested from.  In theory, an attacker could provide
        invalid log content back. You might want to use this if your kubelet serving certificates have expired.

    --limit-bytes=0:
        Maximum bytes of logs to return. Defaults to no limit.

    --max-log-requests=5:
        Specify maximum number of concurrent logs to follow when using by a selector. Defaults to 5.

    --pod-running-timeout=20s:
        The length of time (like 5s, 2m, or 3h, higher than zero) to wait until at least one pod is running

    --prefix=false:
        Prefix each log line with the log source (pod name and container name)

    -p, --previous=false:
        If true, print the logs for the previous instance of the container in a pod if it exists.

    -l, --selector='':
        Selector (label query) to filter on, supports '=', '==', '!=', 'in', 'notin'.(e.g. -l
        key1=value1,key2=value2,key3 in (value3)). Matching objects must satisfy all of the specified label
        constraints.

    --since=0s:
        Only return logs newer than a relative duration like 5s, 2m, or 3h. Defaults to all logs. Only one of
        since-time / since may be used.

    --since-time='':
        Only return logs after a specific date (RFC3339). Defaults to all logs. Only one of since-time / since may be
        used.

    --tail=-1:
        Lines of recent log file to display. Defaults to -1 with no selector, showing all log lines otherwise 10, if a
        selector is provided.

    --timestamps=false:
        Include timestamps on each line in the log output

Usage:
  kubectl logs [-f] [-p] (POD | TYPE/NAME) [-c CONTAINER] [options]

Use "kubectl options" for a list of global command-line options (applies to all commands).
```