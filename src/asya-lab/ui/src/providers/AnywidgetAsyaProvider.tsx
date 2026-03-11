import { useState, useEffect, useCallback, type ReactNode } from "react";
import { AsyaContext } from "./AsyaContext";
import type {
  AsyaContextValue,
  ActorInfo,
  ActorStatus,
  LogLine,
  TaskProgress,
  ConnectionState,
} from "../types";

interface AnywidgetModel {
  get(key: string): unknown;
  set(key: string, value: unknown): void;
  on(event: string, callback: () => void): void;
  off(event: string, callback: () => void): void;
  save_changes(): void;
}

export function AnywidgetAsyaProvider({
  model,
  children,
}: {
  model: AnywidgetModel;
  children: ReactNode;
}) {
  const [actors, setActors] = useState<ActorInfo[]>([]);
  const [statuses, setStatuses] = useState<Map<string, ActorStatus>>(new Map());
  const [logLines, setLogLines] = useState<LogLine[]>([]);
  const [taskProgress, setTaskProgress] = useState<TaskProgress | null>(null);
  const [connectionState] = useState<ConnectionState>("connected");

  useEffect(() => {
    const syncActors = () => setActors((model.get("actors") as ActorInfo[]) || []);
    const syncStatus = () => {
      const raw = model.get("status") as Record<string, ActorStatus> | undefined;
      if (raw) setStatuses(new Map(Object.entries(raw)));
    };
    const syncLogs = () => setLogLines((model.get("logs") as LogLine[]) || []);
    const syncTask = () => setTaskProgress((model.get("task") as TaskProgress) || null);

    syncActors();
    syncStatus();
    syncLogs();
    syncTask();

    model.on("change:actors", syncActors);
    model.on("change:status", syncStatus);
    model.on("change:logs", syncLogs);
    model.on("change:task", syncTask);

    return () => {
      model.off("change:actors", syncActors);
      model.off("change:status", syncStatus);
      model.off("change:logs", syncLogs);
      model.off("change:task", syncTask);
    };
  }, [model]);

  const getActorStatus = useCallback(
    (name: string) => statuses.get(name) ?? null,
    [statuses],
  );

  const value: AsyaContextValue = {
    actors,
    getActorStatus,
    subscribeLogs: () => () => {},
    logLines,
    taskProgress,
    subscribeTask: () => () => {},
    flowName: (model.get("graph") as { flow?: string })?.flow || "",
    context: "jupyter",
    readonly: true,
    connectionState,
  };

  return <AsyaContext.Provider value={value}>{children}</AsyaContext.Provider>;
}
