import { useState, useEffect, useCallback, useRef, type ReactNode } from "react";
import { AsyaContext } from "./AsyaContext";
import type {
  AsyaContextValue,
  ActorInfo,
  ActorStatus,
  LogLine,
  TaskProgress,
  ConnectionState,
} from "../types";

export interface HttpAsyaProviderProps {
  baseUrl: string;
  flowName: string;
  context?: string;
  children: ReactNode;
}

export function HttpAsyaProvider({
  baseUrl,
  flowName,
  context = "local",
  children,
}: HttpAsyaProviderProps) {
  const [actors, setActors] = useState<ActorInfo[]>([]);
  const [actorStatuses, setActorStatuses] = useState<Map<string, ActorStatus>>(new Map());
  const [logLines, setLogLines] = useState<LogLine[]>([]);
  const [taskProgress, setTaskProgress] = useState<TaskProgress | null>(null);
  const [connectionState, setConnectionState] = useState<ConnectionState>("connecting");
  const [connectionError, setConnectionError] = useState<string>();
  const [readonly, setReadonly] = useState(true);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    async function init() {
      try {
        const configRes = await fetch(`${baseUrl}/api/config`);
        if (!configRes.ok) throw new Error(`Config fetch failed: ${configRes.status}`);
        const config = await configRes.json();
        setReadonly(config.readonly ?? true);

        const manifestsRes = await fetch(`${baseUrl}/api/flows/${flowName}/manifests`);
        if (manifestsRes.ok) {
          const manifests = await manifestsRes.json();
          const actorInfos: ActorInfo[] = manifests.map(
            (m: { content: Record<string, unknown> }) => ({
              name:
                ((m.content as Record<string, unknown>)?.metadata as Record<string, unknown>)
                  ?.name || "unknown",
              handler: "",
              image: "",
              transport: "",
              labels: {},
            }),
          );
          setActors(actorInfos);
        }

        setConnectionState("connected");
      } catch (e) {
        setConnectionState("error");
        setConnectionError(e instanceof Error ? e.message : String(e));
      }
    }
    init();
  }, [baseUrl, flowName]);

  useEffect(() => {
    const wsUrl = baseUrl.replace(/^http/, "ws") + "/ws/actors";
    let reconnectTimer: ReturnType<typeof setTimeout>;
    let backoff = 1000;

    function connect() {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnectionState("connected");
        backoff = 1000;
        ws.send(JSON.stringify({ subscribe: actors.map((a) => a.name) }));
      };

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.actor && data.status) {
          setActorStatuses((prev) => {
            const next = new Map(prev);
            next.set(data.actor, data.status);
            return next;
          });
        }
      };

      ws.onclose = () => {
        setConnectionState("reconnecting");
        reconnectTimer = setTimeout(connect, Math.min(backoff, 30000));
        backoff *= 2;
      };

      ws.onerror = () => {
        setConnectionState("degraded");
      };
    }

    connect();

    return () => {
      clearTimeout(reconnectTimer);
      wsRef.current?.close();
    };
  }, [baseUrl, actors]);

  const getActorStatus = useCallback(
    (name: string) => actorStatuses.get(name) ?? null,
    [actorStatuses],
  );

  const subscribeLogs = useCallback(
    (actorName: string) => {
      const eventSource = new EventSource(`${baseUrl}/api/actors/${actorName}/logs`);
      eventSource.onmessage = (event) => {
        const line: LogLine = JSON.parse(event.data);
        setLogLines((prev) => [...prev.slice(-999), line]);
      };
      return () => eventSource.close();
    },
    [baseUrl],
  );

  const subscribeTask = useCallback(
    (taskId: string) => {
      const eventSource = new EventSource(`${baseUrl}/api/gateway/stream/${taskId}`);
      eventSource.onmessage = (event) => {
        setTaskProgress(JSON.parse(event.data));
      };
      return () => eventSource.close();
    },
    [baseUrl],
  );

  const value: AsyaContextValue = {
    actors,
    getActorStatus,
    subscribeLogs,
    logLines,
    taskProgress,
    subscribeTask,
    flowName,
    context,
    readonly,
    connectionState,
    connectionError,
  };

  return <AsyaContext.Provider value={value}>{children}</AsyaContext.Provider>;
}
